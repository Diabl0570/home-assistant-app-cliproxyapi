import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import yaml

MANAGER_PORT = 18317
STRATEGIES = ("round-robin", "fill-first")
# A subset of Go durations, which CLIProxyAPI parses: 1h, 30m, 2h30m, 90s.
TTL = re.compile(r"(?:([0-9]+)h)?(?:([0-9]+)m)?(?:([0-9]+)s)?")
# Devin lists its models as devin/<id> and names GPT-5.6 Sol gpt-5-6-sol.
BLOCKED_MODELS = ["gpt-6-sol", "gpt-5.6-sol", "devin/gpt-6-sol", "devin/gpt-5-6-sol"]
# CLIProxyAPI 8.0.4 looks up OAuth exclusions per provider; there is no global list.
OAUTH_PROVIDERS = ("aistudio", "antigravity", "claude", "codex", "devin", "gemini", "kimi", "meta", "vertex", "xai")
# Provider API key families that support excluded-models, as v8 group names and legacy keys.
API_KEY_FAMILIES = {"gemini": "gemini-api-key", "interactions": "interactions-api-key",
                    "vertex": "vertex-api-key", "codex": "codex-api-key", "claude": "claude-api-key",
                    "xai": "xai-api-key", "meta": "meta-api-key"}


def section(config, key):
    value = config.get(key)
    if value is None:
        value = config[key] = {}
    if not isinstance(value, dict):
        raise ValueError(f"Configuration section {key} must be a mapping")
    return value


def entries(value, name):
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(entry, dict) for entry in value):
        raise ValueError(f"{name} must be a list of mappings")
    return value


def upstream(model):
    """The model CLIProxyAPI sends upstream, without a thinking suffix such as (high)."""
    model = model.strip().lower()
    if model.endswith(")") and "(" in model:
        model = model[:model.rindex("(")]
    return model.strip()


def text(value):
    return value.strip().lower() if isinstance(value, str) else ""


def exclusions(blocked, models, name):
    """The blocked models plus each configured client ID that a request can send to one."""
    models = entries(models, name)
    # CLIProxyAPI 8.0.4 maps each alias and name, exact and without a thinking suffix, to the first entry's model.
    targets = {}
    for model in models:
        target, alias = text(model.get("name")), text(model.get("alias"))
        if target and alias:
            for key in (alias, upstream(alias), target, upstream(target)):
                targets.setdefault(key, target)

    def sends(request):
        return upstream(targets.get(request) or targets.get(upstream(request)) or request)

    # For an API key, CLIProxyAPI matches exclusions against a model's client ID: its alias, or else its name.
    # A request routes by its ID without a thinking suffix, so sol(high) is served through the ID sol.
    ids = []
    for model in models:
        client = text(model.get("alias")) or text(model.get("name"))
        requests = [client, *(key for key in targets if upstream(key) == client)]
        if client and any(sends(request) in blocked for request in requests):
            ids.append(client)
    return list(dict.fromkeys(blocked + ids))


def own(owner, excluded):
    """Rewrite an exclusion field the app owns; nothing blocked leaves no field."""
    if excluded:
        owner["excluded-models"] = excluded
    else:
        owner.pop("excluded-models", None)


def block_models(config, blocked):
    oauth = section(config, "oauth")
    # A present v8 field replaces its legacy field, even when null.
    current = oauth.get("excluded-models") if "excluded-models" in oauth else config.get("oauth-excluded-models")
    config.pop("oauth-excluded-models", None)
    if current is not None and not isinstance(current, dict):
        raise ValueError("oauth.excluded-models must be a mapping")
    # CLIProxyAPI trims and lowercases provider names, so equivalent names share one entry.
    providers = dict.fromkeys([*OAUTH_PROVIDERS, *(str(provider).strip().lower() for provider in current or {})])
    own(oauth, {provider: blocked for provider in providers} if blocked else {})
    # API key credentials ignore the OAuth list, so each provider key group gets its own copy.
    groups = config.get("api-keys")
    groups = groups if isinstance(groups, dict) else {}
    for family, legacy in API_KEY_FAMILIES.items():
        if family not in groups:
            # CLIProxyAPI reads a legacy family only when api-keys has no entry for it.
            for entry in entries(config.get(legacy), legacy):
                own(entry, exclusions(blocked, entry.get("models"), f"{legacy} models"))
            continue
        for group in entries(groups[family], f"api-keys.{family}"):
            own(group, exclusions(blocked, group.get("models"), f"api-keys.{family} models"))
            # A key's own list replaces its group's, so only a key with its own models keeps one.
            for key in entries(group.get("keys"), f"api-keys.{family} keys"):
                models = key.get("models")
                own(key, [] if models is None else exclusions(blocked, models, f"api-keys.{family} models"))


def write(path, value):
    # JSON is valid YAML and cannot interpret user strings as YAML structure.
    descriptor, temporary = tempfile.mkstemp(prefix=".cliproxy-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as output:
            json.dump(value, output, ensure_ascii=False, indent=2, allow_nan=False)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    path.chmod(0o600)


def prepare(data=Path("/data")):
    options = json.loads((data / "options.json").read_text())
    keys = options.get("api_keys")
    password = options.get("management_password")
    logging = options.get("logging", False)
    if not isinstance(keys, list) or not keys or any(
        not isinstance(key, str) or not key.strip() for key in keys
    ):
        raise ValueError("Set at least one nonempty api_keys value in app configuration")
    # CPA Manager Plus trims key files; padding would split proxy and manager credentials.
    if not isinstance(password, str) or len(password) < 24 or password != password.strip():
        raise ValueError("Set management_password to a random password of at least 24 characters "
                         "without leading or trailing spaces")
    if password in keys:
        raise ValueError("Use separate management and client API credentials")
    if not isinstance(logging, bool):
        raise ValueError("logging must be true or false")
    strategy = options.get("routing_strategy", "round-robin")
    affinity = options.get("session_affinity", True)
    ttl = options.get("session_affinity_ttl", "1h")
    retry = options.get("retry_other_accounts", True)
    if strategy not in STRATEGIES:
        raise ValueError("routing_strategy must be round-robin or fill-first")
    if not isinstance(affinity, bool) or not isinstance(retry, bool):
        raise ValueError("session_affinity and retry_other_accounts must be true or false")
    match = TTL.fullmatch(ttl) if isinstance(ttl, str) else None
    if not match or not any(int(part or 0) for part in match.groups()):
        raise ValueError("session_affinity_ttl must be a positive duration such as 1h or 30m")
    blocked = options.get("blocked_models", BLOCKED_MODELS)
    # CLIProxyAPI compares exclusions trimmed and lowercased, and reads * as a wildcard.
    if not isinstance(blocked, list) or any(
        not isinstance(model, str) or not model.strip() or "*" in model for model in blocked
    ):
        raise ValueError("blocked_models must be a list of exact model names")
    blocked = list(dict.fromkeys(model.strip().lower() for model in blocked))
    config_path = data / "cliproxy.yaml"
    config = yaml.safe_load(config_path.read_text()) if config_path.exists() else {}
    if not isinstance(config, dict):
        raise ValueError("Persistent configuration must be a mapping")
    config["config-version"] = 8
    server = section(config, "server")
    server.update({"host": "", "port": 8317})
    section(server, "tls")["enable"] = False
    management = section(config, "management")
    management.update({"allow-remote": True, "secret-key": password,
                       "disable-control-panel": False, "disable-auto-update-panel": True})
    section(config, "access")["api-keys"] = keys
    auths = data / "auths"
    auths.mkdir(mode=0o700, exist_ok=True)
    auths.chmod(0o700)
    section(config, "oauth")["auth-dir"] = str(auths)
    logs = section(section(config, "observability"), "logs")
    logs.update({"debug": logging, "logging-to-file": False, "request-log": False})
    # CPA Manager Plus monitoring reads the usage queue; keep a choice made in the panel.
    section(section(config, "observability"), "usage").setdefault("usage-statistics-enabled", True)
    routing = section(config, "routing")
    routing.update({"strategy": strategy, "session-affinity": affinity,
                    "session-affinity-ttl": ttl})
    # Retrying tries the other accounts for a failed request; off limits it to one account.
    section(routing, "retry").update({"request-retry": 3 if retry else 0,
                                      "max-retry-credentials": 0 if retry else 1})
    block_models(config, blocked)
    write(config_path, config)
    for credential in auths.rglob("*"):
        if credential.is_file():
            credential.chmod(0o600)
    return config_path


def prepare_manager(data=Path("/data"), runtime=None):
    """Return the CPA Manager Plus environment; secrets go in private files, never argv or logs."""
    password = json.loads((data / "options.json").read_text())["management_password"]
    home = data / "cpa-manager-plus"
    home.mkdir(mode=0o700, exist_ok=True)
    home.chmod(0o700)
    runtime = Path(runtime or tempfile.mkdtemp(prefix="cpa-manager-plus-"))
    runtime.chmod(0o700)
    key_file = runtime / "management-key"
    key_file.write_text(password)
    key_file.chmod(0o600)
    environment = {
        "HTTP_ADDR": f"0.0.0.0:{MANAGER_PORT}",
        "USAGE_DATA_DIR": str(home),
        "USAGE_DB_PATH": str(home / "usage.sqlite"),
        "CPA_MANAGER_DATA_KEY_PATH": str(home / "data.key"),
        "CPA_UPSTREAM_URL": "http://127.0.0.1:8317",
        # The management password is both the proxy key and the manager login.
        "CPA_MANAGEMENT_KEY_FILE": str(key_file),
        "CPA_MANAGER_ADMIN_KEY_FILE": str(key_file),
        "CPAMP_UPDATE_CHECK_ENABLED": "false",
    }
    return environment, key_file


def sync_admin_key(binary, environment, key_file):
    """Keep the stored manager login equal to the current management password."""
    database = Path(environment["USAGE_DB_PATH"])
    if not database.exists() or database.stat().st_size == 0:
        return True  # First start: the manager stores the key from the environment.
    result = subprocess.run(
        [binary, "reset-admin-key", "--db-path", str(database), "--admin-key-file", str(key_file)],
        env={**os.environ, **environment}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return result.returncode == 0


def supervise(commands):
    """Run all commands; stop the rest when one exits or the app is stopped."""
    children = []
    stopping = []

    def stop(signum=None, frame=None):
        stopping.append(signum)
        for child in children:
            if child.poll() is None:
                child.terminate()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    for command, environment in commands:
        children.append(subprocess.Popen(command, env={**os.environ, **environment}))
    if stopping:
        stop()
    pid, wait_status = os.wait()
    status = os.waitstatus_to_exitcode(wait_status)
    for child in children:
        if child.pid == pid:
            child.returncode = status
    requested = bool(stopping)
    stop()
    for child in children:
        try:
            child.wait(timeout=20)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
    # A requested stop is clean; any other exit is a failure Home Assistant should see.
    return 0 if requested else max(status, 1)


def main(data=Path("/data"), proxy="/usr/local/bin/cli-proxy-api",
         manager="/usr/local/bin/cpa-manager-plus"):
    try:
        config = prepare(data)
        manager_environment, key_file = prepare_manager(data)
    except (ValueError, OSError, yaml.YAMLError):
        print("CLIProxyAPI configuration invalid: check app options and persistent YAML. "
              "API keys must be nonempty; use a separate management password with 24+ characters "
              "and no leading or trailing spaces; "
              "session_affinity_ttl must be a duration such as 1h or 30m; "
              "blocked_models must list exact model names without *.", file=sys.stderr)
        return 1
    if not sync_admin_key(manager, manager_environment, key_file):
        print("CPA Manager Plus admin key could not be reset to the current management password; "
              "not starting, so the previous password cannot stay valid. Restart the app to retry.",
              file=sys.stderr)
        return 1
    return supervise([
        ([proxy, "-config", str(config)], {}),
        ([manager], manager_environment),
    ])


if __name__ == "__main__":
    os.umask(0o077)
    sys.exit(main())
