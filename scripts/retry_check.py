"""Check retries before the first output against the CLIProxyAPI release pinned in the built image.

A fake provider in this script answers each model with a scripted failure, using only synthetic credentials
and no real provider accounts. The app runs with host networking so the proxy reaches it on 127.0.0.1.
"""
from collections import Counter
import http.client
import http.server
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request

NAME = "ha-cliproxy-retry"
API = "http://127.0.0.1:8317"
PROVIDER_PORT = 18999
KEY = "ci-client-key-12345678901234567890"
PASSWORD = "ci-management-password-123456789012345"
GOOD, BAD = "ci-fake-provider-key-good-1234567890", "ci-fake-provider-key-bad-1234567890"
# CLIProxyAPI waits 5 s after a timeout or 5xx and at least 10 s after a 429, plus up to a quarter (at most 2 s)
# of jitter; a wait over 30 s is never taken. A dropped connection does not cool the account, so it is retried at once.
WAIT, RATE_LIMIT_WAIT, SLACK = 5, 10, 0.5


class Provider(http.server.BaseHTTPRequestHandler):
    """Fails the first call, every call or no call of a model, as its name says; counts calls per model and key."""
    calls = Counter()

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
        model, stream = request["model"], request.get("stream", False)
        key = self.headers.get("Authorization", "").removeprefix("Bearer ")
        Provider.calls[model] += 1
        Provider.calls[model, key] += 1
        first = Provider.calls[model] == 1
        failure = model.split("-")[1]
        if key == BAD or (failure != "never" and (first or model.startswith("always-"))):
            if failure == "drop":
                self.connection.shutdown(socket.SHUT_RDWR)
                self.close_connection = True
                return
            if failure == "break":
                return self.events(model, ["partial"], complete=False)
            status = int(failure) if failure.isdigit() else 503
            return self.reply(status, {"error": {"message": "fake failure", "type": "server_error"}},
                              {"Retry-After": "120"} if model.endswith("-later") else {})
        if stream:
            return self.events(model, ["hello", " world"])
        self.reply(200, {"id": "chatcmpl-fake", "object": "chat.completion", "created": 0, "model": model,
                         "choices": [{"index": 0, "finish_reason": "stop",
                                      "message": {"role": "assistant", "content": "hello world"}}],
                         "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}})

    def reply(self, status, body, headers=None):
        data = json.dumps(body).encode()
        self.send_response(status)
        for name, value in {"Content-Type": "application/json", "Content-Length": str(len(data)), **(headers or {})}.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

    def events(self, model, texts, complete=True):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for text in texts:
            chunk = {"id": "chatcmpl-fake", "object": "chat.completion.chunk", "created": 0, "model": model,
                     "choices": [{"index": 0, "delta": {"role": "assistant", "content": text}, "finish_reason": None}]}
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.flush()
        if complete:
            self.wfile.write(b"data: [DONE]\n\n")
        else:
            # The output has begun; the provider now fails, as a dropped connection.
            time.sleep(0.5)
            self.connection.shutdown(socket.SHUT_RDWR)
        self.close_connection = True

    def log_message(self, *args):
        pass


MODELS = ["once-503", "once-500", "once-502", "once-504", "once-408", "once-429", "once-drop", "always-drop", "always-503",
          "always-400", "always-401", "always-429-later", "stream-503", "stream-break", "cancel-503",
          "failover-never"]


def provider_config(models):
    """One fake account per model, so the cooldown of one never delays another; failover has a failing second key."""
    return {"api-keys": {"openai-compatibility": [{
        "name": f"fake-{model}", "base-url": f"http://127.0.0.1:{PROVIDER_PORT}/v1",
        "keys": [{"api-key": BAD}, {"api-key": GOOD}] if model.startswith("failover-") else [{"api-key": GOOD}],
        "models": [{"name": model, "alias": model}]} for model in models]}}


def chat(model, stream=False, timeout=60, content="ci"):
    """Return status, body text and seconds taken; a broken stream returns what arrived before the break."""
    body = json.dumps({"model": model, "stream": stream, "messages": [{"role": "user", "content": content}]}).encode()
    request = urllib.request.Request(f"{API}/v1/chat/completions", body, {
        "Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}, method="POST")
    start = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = response.status
            try:
                text = response.read().decode()
            except http.client.IncompleteRead as error:
                text = error.partial.decode()
    except urllib.error.HTTPError as error:
        status, text = error.code, error.read().decode()
    return status, text, time.monotonic() - start


def ready(models):
    for attempt in range(60):
        try:
            request = urllib.request.Request(f"{API}/v1/models", headers={"Authorization": f"Bearer {KEY}"})
            with urllib.request.urlopen(request, timeout=2) as response:
                listed = {model["id"] for model in json.loads(response.read())["data"]}
            if set(models) <= listed:
                return
        except OSError:
            pass
        time.sleep(1)
    raise AssertionError("proxy did not list the fake models")


def contents(text):
    """The streamed text deltas, in order."""
    deltas = []
    for line in text.splitlines():
        if line.startswith("data: {"):
            for choice in json.loads(line[6:]).get("choices", []):
                deltas.append((choice.get("delta") or {}).get("content") or "")
    return [delta for delta in deltas if delta]


def check_retries():
    calls = Provider.calls
    for status in (503, 500, 502, 504, 408):
        code, text, seconds = chat(f"once-{status}")
        assert code == 200 and "hello world" in text, (status, code, text)
        assert calls[f"once-{status}"] == 2, (status, calls)
        assert WAIT - SLACK <= seconds < WAIT + 2 + 5, (status, seconds)
    code, text, seconds = chat("once-429")
    assert code == 200 and calls["once-429"] == 2, (code, calls)
    assert RATE_LIMIT_WAIT - SLACK <= seconds < RATE_LIMIT_WAIT + 2 + 5, seconds
    # A connection that closes before any answer is unavailable: retried at once, at most three times.
    code, text, seconds = chat("once-drop")
    assert code == 200 and calls["once-drop"] == 2 and seconds < WAIT - SLACK, (code, calls, seconds)
    code, text, seconds = chat("always-drop")
    assert code >= 500 and calls["always-drop"] == 4 and seconds < WAIT - SLACK, (code, calls, seconds)
    # Bounded: three retries after the first attempt, each after its wait, then the provider's error.
    code, text, seconds = chat("always-503", timeout=120)
    assert code == 503 and calls["always-503"] == 4, (code, calls)
    assert 3 * (WAIT - SLACK) <= seconds < 3 * (WAIT + 2) + 10, seconds
    # Not transient: answered at once without a retry.
    for model, status in (("always-400", 400), ("always-401", 401)):
        code, text, seconds = chat(model)
        assert code == status and calls[model] == 1 and seconds < WAIT - SLACK, (model, code, calls, seconds)
    # A rate limit asking for longer than the 30 s cap ends the request at once instead of waiting.
    code, text, seconds = chat("always-429-later")
    assert code == 429 and calls["always-429-later"] == 1 and seconds < WAIT - SLACK, (code, calls, seconds)


def check_streams():
    calls = Provider.calls
    code, text, seconds = chat("stream-503", stream=True)
    assert code == 200 and calls["stream-503"] == 2 and seconds >= WAIT - SLACK, (code, calls, seconds)
    assert contents(text) == ["hello", " world"] and text.count("[DONE]") == 1, text
    # Output has begun: the failure reaches the client and the request is never replayed.
    code, text, seconds = chat("stream-break", stream=True)
    assert contents(text) == ["partial"], text
    time.sleep(2 * WAIT)
    assert calls["stream-break"] == 1, calls
    # A client that disconnects during the wait ends the request: no further attempt follows.
    connection = http.client.HTTPConnection(API.removeprefix("http://"), timeout=10)
    connection.request("POST", "/v1/chat/completions", json.dumps({
        "model": "cancel-503", "messages": [{"role": "user", "content": "ci"}]}),
        {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"})
    time.sleep(2)
    assert calls["cancel-503"] == 1, calls
    connection.close()
    time.sleep(2 * WAIT)
    assert calls["cancel-503"] == 1, calls
    # Another account still takes over at once, within the same round. Round-robin starts the two new
    # conversations on different accounts, so one of them fails on the bad account first.
    for content in ("first conversation", "second conversation"):
        code, text, seconds = chat("failover-never", content=content)
        assert code == 200 and seconds < WAIT - SLACK, (code, seconds)
    assert calls["failover-never", BAD] == 1 and calls["failover-never", GOOD] == 2, calls


def check_without_waiting(suffix, drops):
    """With retry_before_output or retry_other_accounts off, a lone account's 503 is returned at once.

    A dropped connection still gets the immediate retries retry_other_accounts allows, as before this option.
    """
    calls = Provider.calls
    code, text, seconds = chat(f"always-503-{suffix}")
    assert code == 503 and calls[f"always-503-{suffix}"] == 1 and seconds < WAIT - SLACK, (code, calls, seconds)
    code, text, seconds = chat(f"always-drop-{suffix}")
    assert code >= 500 and calls[f"always-drop-{suffix}"] == drops and seconds < WAIT - SLACK, (code, calls, seconds)


def run(start):
    """start(data) launches the app on the prepared /data directory and returns a function that stops it."""
    server = http.server.ThreadingHTTPServer(("127.0.0.1", PROVIDER_PORT), Provider)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        for options, models, checks in [
            ({}, MODELS, [check_retries, check_streams]),
            ({"retry_before_output": False}, ["always-503-off", "always-drop-off"],
             [lambda: check_without_waiting("off", 4)]),
            ({"retry_other_accounts": False}, ["always-503-single", "always-drop-single"],
             [lambda: check_without_waiting("single", 1)]),
        ]:
            with tempfile.TemporaryDirectory() as directory:
                data = Path(directory)
                (data / "options.json").write_text(json.dumps({"api_keys": [KEY], "management_password": PASSWORD,
                                                               **options}))
                (data / "cliproxy.yaml").write_text(json.dumps(provider_config(models)))
                stop = start(data)
                try:
                    ready(models)
                    for check in checks:
                        check()
                finally:
                    stop()
        print("retries:", json.dumps({str(key): value for key, value in Provider.calls.items()
                                       if isinstance(key, str)}, sort_keys=True))
    finally:
        server.shutdown()


def docker(data):
    subprocess.run(["docker", "run", "-d", "--name", NAME, "--network", "host", "-v", f"{data}:/data",
                    "ha-cliproxy-test"], check=True)

    def stop():
        subprocess.run(["docker", "logs", NAME], check=False)
        subprocess.run(["docker", "exec", NAME, "chmod", "-R", "a+rwX", "/data"], check=False)
        subprocess.run(["docker", "rm", "-f", NAME], check=False)
    return stop


if __name__ == "__main__":
    run(docker)
