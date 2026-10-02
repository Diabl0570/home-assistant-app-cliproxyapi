import json
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.request
import urllib.error

with tempfile.TemporaryDirectory() as directory:
    data = Path(directory)
    key = "ci-client-key-12345678901234567890"
    password = "ci-management-password-123456789012345"
    rotated = "ci-rotated-management-password-1234567890"
    def write_options(management_password):
        (data / "options.json").write_text(json.dumps({"api_keys": [key], "management_password": management_password, "logging": False}))
    write_options(password)
    subprocess.run(["docker", "run", "-d", "--name", "ha-cliproxy-smoke", "-p", "127.0.0.1:18317:8317", "-p", "127.0.0.1:28317:18317", "-v", f"{data}:/data", "ha-cliproxy-test"], check=True)
    def status(url, token=None):
        request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"} if token else {})
        try:
            with urllib.request.urlopen(request, timeout=2) as response:
                return response.status
        except urllib.error.HTTPError as error:
            return error.code
    def api(token=None):
        return status("http://127.0.0.1:18317/v1/models", token)
    def manager(token=None):
        # CPA Manager Plus forwards this to the proxy management API with the stored connection.
        return status("http://127.0.0.1:28317/v0/management/config", token)
    def ready(management_password):
        for attempt in range(60):
            try:
                if api(key) == 200 and manager(management_password) == 200:
                    return
            except (OSError, urllib.error.URLError):
                pass
            time.sleep(1)
        raise AssertionError("API or CPA Manager Plus did not become ready")
    try:
        ready(password)
        assert api() == 401
        assert api("wrong-key") == 401
        assert manager() == 401
        assert manager("wrong-password-123456789012345") == 401
        assert status("http://127.0.0.1:28317/management.html") == 200
        subprocess.run(["docker", "exec", "ha-cliproxy-smoke", "sh", "-c", "printf '{}' > /data/auths/persistence-marker.json"], check=True)
        subprocess.run(["docker", "restart", "ha-cliproxy-smoke"], check=True)
        ready(password)
        assert api() == 401
        assert subprocess.check_output(["docker", "exec", "ha-cliproxy-smoke", "cat", "/data/auths/persistence-marker.json"], text=True) == "{}"
        write_options(rotated)
        subprocess.run(["docker", "restart", "ha-cliproxy-smoke"], check=True)
        ready(rotated)
        assert manager(password) == 401
        logs = subprocess.run(["docker", "logs", "ha-cliproxy-smoke"], capture_output=True, text=True, check=True)
        output = logs.stdout + logs.stderr
        assert password not in output and rotated not in output and key not in output, "secret printed to logs"
    finally:
        subprocess.run(["docker", "logs", "ha-cliproxy-smoke"], check=False)
        subprocess.run(["docker", "exec", "ha-cliproxy-smoke", "chmod", "-R", "a+rwX", "/data"], check=False)
        subprocess.run(["docker", "rm", "-f", "ha-cliproxy-smoke"], check=False)
