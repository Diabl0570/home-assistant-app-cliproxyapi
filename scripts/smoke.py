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
    (data / "options.json").write_text(json.dumps({"api_keys": [key], "management_password": "ci-management-password-123456789012345", "logging": False}))
    subprocess.run(["docker", "run", "-d", "--name", "ha-cliproxy-smoke", "-p", "127.0.0.1:18317:8317", "-v", f"{data}:/data", "ha-cliproxy-test"], check=True)
    def status(token=None):
        request = urllib.request.Request("http://127.0.0.1:18317/v1/models", headers={"Authorization": f"Bearer {token}"} if token else {})
        try:
            with urllib.request.urlopen(request, timeout=2) as response:
                return response.status
        except urllib.error.HTTPError as error:
            return error.code
    def ready():
        for attempt in range(60):
            try:
                if status(key) == 200:
                    return
            except (OSError, urllib.error.URLError):
                pass
            time.sleep(1)
        raise AssertionError("API did not become ready")
    try:
        ready()
        assert status() == 401
        assert status("wrong-key") == 401
        subprocess.run(["docker", "exec", "ha-cliproxy-smoke", "sh", "-c", "printf '{}' > /data/auths/persistence-marker.json"], check=True)
        subprocess.run(["docker", "restart", "ha-cliproxy-smoke"], check=True)
        ready()
        assert status() == 401
        assert subprocess.check_output(["docker", "exec", "ha-cliproxy-smoke", "cat", "/data/auths/persistence-marker.json"], text=True) == "{}"
    finally:
        subprocess.run(["docker", "logs", "ha-cliproxy-smoke"], check=False)
        subprocess.run(["docker", "exec", "ha-cliproxy-smoke", "chmod", "-R", "a+rwX", "/data"], check=False)
        subprocess.run(["docker", "rm", "-f", "ha-cliproxy-smoke"], check=False)
