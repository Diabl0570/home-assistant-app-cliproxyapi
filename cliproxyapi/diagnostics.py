"""Read-only failed-request diagnostics, a sidecar next to CLIProxyAPI and CPA Manager Plus.

It answers one GET with the recent failed requests from CPA Manager Plus's request history, reduced to an
allowlist of facts. It never writes to the proxy or the manager. When the manager is unreachable or its
interface has changed, it answers that diagnostics is unavailable; the proxy is never involved.
"""
from datetime import datetime, timezone
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import re
import sys
import threading
import time
from urllib.parse import parse_qs, urlsplit
import urllib.error
import urllib.request

PORT = 18318
PATH = "/diagnostics/failures"
# The manager's own request-history query, as its Monitoring page uses it.
MANAGER = "http://127.0.0.1:18317"
ANALYTICS = "/v0/management/monitoring/analytics"
TIMEOUT = 10
DEFAULT_HOURS, MAX_HOURS = 24, 168
DEFAULT_LIMIT, MAX_LIMIT = 50, 200

MODEL = re.compile(r"[\w.:/()+-]{1,96}")
PROVIDER = re.compile(r"[a-z0-9_.-]{1,40}")
LABEL = re.compile(r"[\w .()+-]{1,40}")
TOKEN = re.compile(r"[A-Za-z0-9_.:-]{1,80}")
# Account labels can be emails or keys; these shapes fall back to a hash instead.
SECRETISH = re.compile(r"[A-Za-z0-9_-]{20,}|\d{6,}")
# CLIProxyAPI 8.0.10 gives every API key of a provider the same label, so these name no account and also hash.
GENERATED = frozenset(provider + "-apikey" for provider in
                      ("gemini", "interactions", "claude", "codex", "xai", "meta", "vertex"))
# The fields diagnostics reads from a CPA Manager Plus 1.14.2 event that may be absent but not null.
STRINGS = ("request_id", "auth_label_snapshot", "auth_index", "source_hash", "auth_provider_snapshot")
# The provider's own error message can quote the prompt, so each class has a fixed description instead.
MESSAGES = {
    "rate_limited": "Rate limited by the provider",
    "overloaded": "Provider overloaded",
    "unavailable": "Provider unavailable",
    "timeout": "Request timed out",
    "unauthorized": "Account not authorized by the provider",
    "forbidden": "Access forbidden by the provider",
    "bad_request": "Request rejected by the provider",
    "not_found": "Model or endpoint not found",
    "server_error": "Provider server error",
    "client_error": "Request failed with a client error",
    "interrupted": "Request ended without an upstream status",
}


class Unavailable(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def text(value, pattern):
    if isinstance(value, str) and pattern.fullmatch(value.strip()):
        return value.strip()
    return None


def integer(value):
    return isinstance(value, int) and not isinstance(value, bool)


def count(value):
    return value if integer(value) and value >= 0 else None


def account(row):
    """The configured account label, or a stable short hash; never an email or key."""
    label = text(row.get("auth_label_snapshot"), LABEL)
    if label and label not in GENERATED and not SECRETISH.search(label):
        return label
    for field in ("auth_index", "source_hash"):
        value = row.get(field)
        if isinstance(value, str) and value.strip():
            return "acct-" + hashlib.sha256(value.strip().encode()).hexdigest()[:10]
    return None


def classify(status):
    if status in (None, 0, 499):
        return "interrupted"
    return {400: "bad_request", 401: "unauthorized", 403: "forbidden", 404: "not_found",
            408: "timeout", 429: "rate_limited", 503: "unavailable", 504: "timeout", 529: "overloaded"}.get(
        status, "server_error" if status >= 500 else "client_error")


def compatible(row, from_ms, to_ms):
    """Whether one event is a failure in the requested window, with the field types diagnostics reads."""
    return (isinstance(row, dict) and row.get("failed") is True and isinstance(row.get("model"), str)
            and integer(row.get("timestamp_ms")) and from_ms <= row["timestamp_ms"] <= to_ms
            and all(isinstance(row.get(field, ""), str) for field in STRINGS)
            and integer(row.get("output_tokens", 0))
            and all(row.get(field) is None or integer(row[field]) for field in ("fail_status_code", "latency_ms"))
            and (row.get("stream") is None or isinstance(row["stream"], bool)))


def fact(row):
    """The allowlisted facts of one failed request; every other upstream field is dropped."""
    status = count(row.get("fail_status_code"))
    error = classify(status)
    return {
        "time": datetime.fromtimestamp(row["timestamp_ms"] / 1000, timezone.utc)
                        .isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "model": text(row["model"], MODEL),
        "provider": text(row.get("auth_provider_snapshot"), PROVIDER),
        "account": account(row),
        "status": status,
        "error": error,
        "message": MESSAGES[error],
        "streamed": row.get("stream"),
        "output_tokens": count(row.get("output_tokens")),
        "duration_ms": count(row.get("latency_ms")),
        "request_id": text(row.get("request_id"), TOKEN),
    }


def failures(payload, from_ms, to_ms, limit):
    """Check the manager's answer against the interface and filter diagnostics asked for."""
    events = payload.get("events") if isinstance(payload, dict) else None
    items = events.get("items") if isinstance(events, dict) else None
    # A row outside the request, such as a success, means the manager ignored or changed a filter.
    if (not isinstance(items, list) or len(items) > limit or not isinstance(events.get("has_more"), bool)
            or not all(compatible(row, from_ms, to_ms) for row in items)):
        raise Unavailable("interface_incompatible")
    return [fact(row) for row in items], events["has_more"]


def query(admin_key, hours, limit, now_ms, manager=MANAGER):
    from_ms = now_ms - hours * 3_600_000
    body = {"from_ms": from_ms, "to_ms": now_ms, "now_ms": now_ms, "time_zone": "UTC",
            "filters": {"failed_only": True}, "include": {"events_page": {"limit": limit}}}
    request = urllib.request.Request(manager + ANALYTICS, data=json.dumps(body).encode(), method="POST",
                                     headers={"Authorization": f"Bearer {admin_key}",
                                              "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            payload = json.loads(response.read(8 * 1024 * 1024))
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            raise Unavailable("manager_unauthorized") from None
        if error.code >= 500:
            raise Unavailable("manager_error") from None
        raise Unavailable("interface_incompatible") from None
    except ValueError:
        raise Unavailable("interface_incompatible") from None
    except OSError:
        raise Unavailable("manager_unreachable") from None
    return failures(payload, from_ms, now_ms, limit)


def number(values, name, default, maximum):
    raw = values.get(name)
    if raw is None:
        return default
    if len(raw) != 1 or not (raw[0].isascii() and raw[0].isdigit()) or not 1 <= int(raw[0]) <= maximum:
        raise ValueError(f"{name} must be a whole number from 1 to {maximum}")
    return int(raw[0])


class Diagnostics:
    def __init__(self, digests, admin_key, manager=MANAGER):
        self.digests = digests
        self.admin_key = admin_key
        self.manager = manager
        # One manager query at a time keeps diagnostics from loading the manager.
        self.lock = threading.Lock()

    def authorized(self, header):
        scheme, _, key = (header or "").partition(" ")
        if scheme.lower() != "bearer" or not key.strip():
            return False
        digest = hashlib.sha256(key.strip().encode()).hexdigest()
        return any([hmac.compare_digest(digest, allowed) for allowed in self.digests])

    def answer(self, method, target, authorization):
        """Return the HTTP status and JSON body for one request."""
        url = urlsplit(target)
        if url.path != PATH:
            return 404, {"error": "not_found"}
        if method != "GET":
            return 405, {"error": "method_not_allowed"}
        if not self.authorized(authorization):
            return 401, {"error": "unauthorized"}
        try:
            values = parse_qs(url.query, keep_blank_values=True)
            if set(values) - {"hours", "limit"}:
                raise ValueError("only hours and limit are supported")
            hours = number(values, "hours", DEFAULT_HOURS, MAX_HOURS)
            limit = number(values, "limit", DEFAULT_LIMIT, MAX_LIMIT)
        except ValueError as error:
            return 400, {"error": "bad_request", "detail": str(error)}
        if not self.lock.acquire(timeout=TIMEOUT):
            return 503, {"status": "unavailable", "reason": "busy"}
        try:
            now_ms = int(time.time() * 1000)
            items, more = query(self.admin_key, hours, limit, now_ms, self.manager)
        except Unavailable as error:
            return 503, {"status": "unavailable", "reason": error.reason}
        finally:
            self.lock.release()
        return 200, {"status": "ok", "hours": hours, "limit": limit, "truncated": more, "failures": items}


class Handler(BaseHTTPRequestHandler):
    diagnostics = None
    timeout = TIMEOUT
    server_version = "diagnostics"
    sys_version = ""

    def respond(self):
        try:
            status, body = self.diagnostics.answer(self.command, self.path, self.headers.get("Authorization"))
        except Exception:
            status, body = 500, {"status": "unavailable", "reason": "internal_error"}
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    do_GET = do_HEAD = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = respond

    def log_message(self, format, *args):
        pass  # No request log: it would carry client addresses and query strings into the app log.


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        # Answers already turn their own errors into a 500, so what reaches here is a client that hung up or
        # timed out. The default report would print its address and a traceback into the app log.
        pass


def serve(diagnostics, address=("0.0.0.0", PORT)):
    handler = type("BoundHandler", (Handler,), {"diagnostics": diagnostics})
    return Server(address, handler)


def main(environ=os.environ):
    try:
        digests = json.loads(open(environ["DIAGNOSTICS_KEYS_FILE"]).read())
        admin_key = open(environ["DIAGNOSTICS_ADMIN_KEY_FILE"]).read()
        if not isinstance(digests, list) or not digests or not admin_key:
            raise ValueError
    except (KeyError, OSError, ValueError):
        print("Diagnostics could not read its keys and is off; the proxy is not affected.", file=sys.stderr)
        return 1
    serve(Diagnostics(digests, admin_key)).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
