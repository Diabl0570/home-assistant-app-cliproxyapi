"""Check diagnostics against the CLIProxyAPI and CPA Manager Plus releases pinned in the built image.

A fake provider inside the container answers every request with an overload error carrying fake secrets,
so a real failed request flows from the proxy through the manager's request history to diagnostics,
using only synthetic credentials and no real provider accounts.
"""
import json
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

NAME = "ha-cliproxy-diagnostics"
KEY = "ci-client-key-12345678901234567890"
PASSWORD = "ci-management-password-123456789012345"
DIAGNOSTICS_KEY = "ci-diagnostics-key-1234567890123456789"
PROVIDER_KEY = "ci-fake-provider-key-1234567890abcdef"
PROMPT = "ci-prompt-marker-must-not-appear"
EMAIL = "someone@example.com"
SECRETS = [KEY, PASSWORD, DIAGNOSTICS_KEY, PROVIDER_KEY, PROMPT, EMAIL]
FIELDS = {"time", "model", "provider", "account", "status", "error", "message", "streamed", "output_tokens",
          "duration_ms", "request_id"}
# Answers everything with 529 and an Anthropic-style overload body naming an email and a key.
FAKE_PROVIDER = f"""
import http.server, json
body = json.dumps({{"type": "error", "error": {{"type": "overloaded_error",
    "message": "Overloaded for {EMAIL}, key {PROVIDER_KEY}"}}}}).encode()
class Handler(http.server.BaseHTTPRequestHandler):
    def answer(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.send_response(529)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    do_GET = do_POST = answer
    def log_message(self, *args):
        pass
http.server.HTTPServer(("127.0.0.1", 18999), Handler).serve_forever()
"""
# Runs inside the container: the real diagnostics module against the real manager, at a path it lacks.
CHANGED_INTERFACE = f"""
import hashlib, sys
sys.path.insert(0, "/usr/local/bin")
import diagnostics
diagnostics.ANALYTICS = "/v0/management/monitoring/changed"
service = diagnostics.Diagnostics([hashlib.sha256(b"{DIAGNOSTICS_KEY}").hexdigest()], "{PASSWORD}")
print(service.answer("GET", diagnostics.PATH, "Bearer {DIAGNOSTICS_KEY}")[1]["reason"])
"""
# Runs inside the container: kills only the sidecar run.py starts, never this script or another process.
STOP_DIAGNOSTICS = """
import os, signal
for pid in filter(str.isdigit, os.listdir("/proc")):
    if int(pid) == os.getpid():
        continue
    try:
        argv = open(f"/proc/{pid}/cmdline", "rb").read().split(b"\\0")
    except OSError:
        continue
    if (len(argv) > 1 and os.path.basename(argv[0]).startswith(b"python")
            and argv[1] == b"/usr/local/bin/diagnostics.py"):
        os.kill(int(pid), signal.SIGKILL)
"""


def request(url, token=None, method="GET", body=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    if body is not None:
        headers["Content-Type"] = "application/json"
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data, headers, method=method), timeout=30) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()


def api(token=None):
    return request("http://127.0.0.1:18317/v1/models", token)[0]


def diagnostics(token=DIAGNOSTICS_KEY, method="GET", query=""):
    return request(f"http://127.0.0.1:38318/diagnostics/failures{query}", token, method)


def ready(check):
    for attempt in range(60):
        try:
            if check():
                return
        except OSError:
            pass
        time.sleep(1)
    raise AssertionError("container did not become ready")


def refused():
    try:
        diagnostics()
    except OSError:
        return True
    return False


with tempfile.TemporaryDirectory() as directory:
    data = Path(directory)
    def write_options(diagnostics_keys):
        (data / "options.json").write_text(json.dumps({"api_keys": [KEY], "management_password": PASSWORD,
                                                       "diagnostics_keys": diagnostics_keys}))
    write_options([])
    (data / "cliproxy.yaml").write_text(json.dumps({"api-keys": {"openai-compatibility": [{
        "name": "fake", "base-url": "http://127.0.0.1:18999/v1", "keys": [{"api-key": PROVIDER_KEY}],
        "models": [{"name": "diag-fake-model", "alias": "diag-fake-model"}]}]}}))
    subprocess.run(["docker", "run", "-d", "--name", NAME, "-p", "127.0.0.1:18317:8317",
                    "-p", "127.0.0.1:38318:18318", "-v", f"{data}:/data", "ha-cliproxy-test"], check=True)
    try:
        # Off by default: nothing listens without diagnostics_keys.
        ready(lambda: api(KEY) == 200)
        assert refused(), "diagnostics listens without diagnostics_keys"
        write_options([DIAGNOSTICS_KEY])
        subprocess.run(["docker", "restart", NAME], check=True)
        ready(lambda: api(KEY) == 200 and diagnostics()[0] == 200)
        for token in [None, "wrong-key-123456789012345678", KEY, PASSWORD]:
            assert diagnostics(token)[0] == 401, "diagnostics accepted another credential"
        for method in ["POST", "PUT", "PATCH", "DELETE"]:
            assert diagnostics(method=method)[0] == 405, f"diagnostics allowed {method}"
        assert request("http://127.0.0.1:38318/v0/management/config", DIAGNOSTICS_KEY)[0] == 404
        # The diagnostics key is no client or management credential.
        assert api(DIAGNOSTICS_KEY) == 401
        subprocess.run(["docker", "exec", "-d", NAME, "python3", "-c", FAKE_PROVIDER], check=True)
        time.sleep(1)
        status, _ = request("http://127.0.0.1:18317/v1/chat/completions", KEY, "POST",
                            {"model": "diag-fake-model", "messages": [{"role": "user", "content": PROMPT}]})
        assert status >= 400, f"fake provider request unexpectedly returned {status}"
        failures = []
        for attempt in range(60):
            status, text = diagnostics(query="?hours=1&limit=10")
            assert status == 200, f"diagnostics answered {status}: {text}"
            failures = json.loads(text)["failures"]
            if failures:
                break
            time.sleep(1)
        assert failures, "the failed request did not reach diagnostics"
        assert all(set(failure) == FIELDS for failure in failures), failures
        failure = failures[0]
        assert failure["model"] == "diag-fake-model", failure
        assert failure["status"] == 529 and failure["error"] == "overloaded", failure
        assert failure["message"] == "Provider overloaded", failure
        assert isinstance(failure["duration_ms"], int), failure
        assert not any(secret in text for secret in SECRETS), "diagnostics returned a secret or prompt"
        print("diagnostics:", json.dumps(failure))
        reason = subprocess.check_output(["docker", "exec", NAME, "python3", "-c", CHANGED_INTERFACE], text=True)
        assert reason.strip() == "interface_incompatible", reason
        # Diagnostics stopping leaves the proxy and the manager running.
        subprocess.run(["docker", "exec", NAME, "python3", "-c", STOP_DIAGNOSTICS], check=True)
        time.sleep(2)
        assert refused(), "diagnostics still answers after being stopped"
        assert api(KEY) == 200, "proxy stopped with diagnostics"
        running = subprocess.check_output(["docker", "inspect", "-f", "{{.State.Running}}", NAME], text=True)
        assert running.strip() == "true", "app stopped with diagnostics"
        logs = subprocess.run(["docker", "logs", NAME], capture_output=True, text=True, check=True)
        assert not any(secret in logs.stdout + logs.stderr for secret in SECRETS[:3]), "secret printed to logs"
    finally:
        subprocess.run(["docker", "logs", NAME], check=False)
        subprocess.run(["docker", "exec", NAME, "chmod", "-R", "a+rwX", "/data"], check=False)
        subprocess.run(["docker", "rm", "-f", NAME], check=False)
