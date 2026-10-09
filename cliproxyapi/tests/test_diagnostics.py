from contextlib import redirect_stderr
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import io
import json
from pathlib import Path
import socket
import struct
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

spec = importlib.util.spec_from_file_location("diagnostics", Path(__file__).parents[1] / "diagnostics.py")
diagnostics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diagnostics)
spec = importlib.util.spec_from_file_location("startup", Path(__file__).parents[1] / "run.py")
startup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(startup)

KEY = "a-diagnostics-key-123456789012345"
ADMIN = "a-separate-random-password-12345"
# Whitespace Go's strings.TrimSpace removes from CLIProxyAPI client keys and CPA Manager Plus key files.
PADDING = [" ", "\t", "\n", "\r\n", "\v", "\f", "\u0085", "\u00a0", "\u2003", "\u3000", " \t\u00a0\n"]
SECRET = "sk-live-0123456789abcdefghijklmnop"
FIELDS = {"time", "model", "provider", "account", "status", "error", "message", "streamed", "output_tokens",
          "duration_ms", "request_id"}
EVENT_MS = 1_767_323_045_000
NOW_MS = EVENT_MS + 60_000
# CPA Manager Plus keeps the provider's error body summary; it can quote the prompt, an email and a key.
SUMMARY = json.dumps({"error": {"type": "rate_limit_error", "message": (
    "Invalid prompt: send payroll to Alice at person@example.com using " + SECRET)}})


def row(**fields):
    """A failed event as CPA Manager Plus 1.14.2 returns it, with secrets in every field diagnostics drops."""
    return {
        "request_id": "req_01", "event_hash": "e" * 64, "timestamp_ms": EVENT_MS,
        "model": "gpt-6.1-sol", "requested_model": "secret-requested", "session_id": SECRET,
        "access_token_sha256": "f" * 64, "stream": True, "endpoint": "/v1/responses", "method": "POST",
        "path": "/v1/responses?key=" + SECRET, "client_ip": "192.168.1.20", "x_forwarded_for": "10.0.0.1",
        "user_agent": "agent " + SECRET, "auth_index": "a1b2c3", "source": "person@example.com",
        "source_hash": "s" * 16, "api_key_hash": "k" * 16, "account_snapshot": "person@example.com",
        "auth_label_snapshot": "Work account", "auth_file_snapshot": "codex-person@example.com.json",
        "auth_provider_snapshot": "codex", "auth_account_id_snapshot": "acct-123456789",
        "input_tokens": 100, "output_tokens": 7, "latency_ms": 1234, "ttft_ms": 200, "failed": True,
        "fail_status_code": 429, "fail_summary": SUMMARY, "header_error_kind": "rate_limit_error",
        "header_trace_id": SECRET, "response_metadata": {"headers": {"authorization": "Bearer " + SECRET}},
        **fields,
    }


def without(*names):
    """A failed event lacking the named fields."""
    event = row()
    for name in names:
        del event[name]
    return event


def page(*items, has_more=False):
    return {"events": {"items": list(items), "has_more": has_more}}


class Manager(BaseHTTPRequestHandler):
    """A fake CPA Manager Plus that records requests and, once released, answers with the configured reply."""

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append((self.command, self.path, self.headers.get("Authorization"), body))
        self.server.released.wait(10)
        status, payload = self.server.reply
        data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_PUT = do_PATCH = do_DELETE = do_POST

    def log_message(self, *args):
        pass


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.manager = ThreadingHTTPServer(("127.0.0.1", 0), Manager)
        self.manager.requests = []
        self.manager.reply = (200, page(row()))
        self.manager.released = threading.Event()
        self.manager.released.set()
        threading.Thread(target=self.manager.serve_forever, daemon=True).start()
        self.addCleanup(self.manager.server_close)
        self.addCleanup(self.manager.shutdown)
        url = f"http://127.0.0.1:{self.manager.server_address[1]}"
        self.service = diagnostics.Diagnostics([hashlib.sha256(KEY.encode()).hexdigest()], ADMIN, url)
        clock = patch.object(diagnostics.time, "time", return_value=NOW_MS / 1000)
        clock.start()
        self.addCleanup(clock.stop)

    def get(self, target=diagnostics.PATH, key=KEY, method="GET"):
        status, body = self.service.answer(method, target, f"Bearer {key}" if key else None)
        return status, body, json.dumps(body)

    def test_only_a_diagnostics_key_is_accepted(self):
        for authorization in [None, "", "Bearer", "Bearer ", f"Basic {KEY}", f"Bearer {ADMIN}",
                              f"Bearer {KEY}x", "Bearer wrong"]:
            with self.subTest(authorization=authorization):
                status, body = self.service.answer("GET", diagnostics.PATH, authorization)
                self.assertEqual((status, body), (401, {"error": "unauthorized"}))
        self.assertEqual(self.manager.requests, [])
        self.assertEqual(self.get()[0], 200)

    def test_one_read_only_get_endpoint(self):
        for method in ["POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]:
            with self.subTest(method=method):
                self.assertEqual(self.get(method=method)[0], 405)
        for target in ["/", "/v0/management/config", diagnostics.PATH + "/x", "/diagnostics"]:
            with self.subTest(target=target):
                self.assertEqual(self.get(target)[0], 404)
        self.assertEqual(self.manager.requests, [])

    def test_queries_the_manager_for_recent_failures_only(self):
        status, body, _ = self.get()
        self.assertEqual(status, 200)
        self.assertEqual((body["status"], body["hours"], body["limit"], body["truncated"]), ("ok", 24, 50, False))
        [(method, path, authorization, request)] = self.manager.requests
        self.assertEqual((method, path, authorization), ("POST", diagnostics.ANALYTICS, f"Bearer {ADMIN}"))
        self.assertEqual(request["filters"], {"failed_only": True})
        self.assertEqual(request["include"], {"events_page": {"limit": 50}})
        self.assertEqual((request["from_ms"], request["to_ms"]), (NOW_MS - 24 * 3_600_000, NOW_MS))
        self.get(diagnostics.PATH + "?hours=168&limit=200")
        self.assertEqual(self.manager.requests[-1][3]["include"]["events_page"]["limit"], 200)
        self.assertEqual(self.manager.requests[-1][3]["to_ms"] - self.manager.requests[-1][3]["from_ms"],
                         168 * 3_600_000)

    def test_bounds_are_enforced(self):
        for query in ["hours=0", "hours=169", "limit=0", "limit=201", "limit=-1", "limit=1.5", "limit=",
                      "limit=1&limit=2", "hours=²", "since=1", "model=x"]:
            with self.subTest(query=query):
                self.assertEqual(self.get(diagnostics.PATH + "?" + query)[0], 400)
        self.assertEqual(self.manager.requests, [])

    def test_only_allowlisted_facts_are_returned(self):
        status, body, text = self.get()
        self.assertEqual(status, 200)
        [failure] = body["failures"]
        self.assertEqual(failure, {
            "time": "2026-01-02T03:04:05.000Z", "model": "gpt-6.1-sol", "provider": "codex",
            "account": "Work account", "status": 429, "error": "rate_limited",
            "message": "Rate limited by the provider", "streamed": True, "output_tokens": 7, "duration_ms": 1234,
            "request_id": "req_01",
        })
        for leaked in [SECRET, "person@example.com", "192.168.1.20", "10.0.0.1", "secret-requested", "f" * 64,
                       "k" * 16, "acct-123456789", "/v1/responses", "rate_limit_error"]:
            self.assertNotIn(leaked, text)

    def test_unexpected_and_nested_upstream_fields_never_pass_through(self):
        self.manager.reply = (200, {"events": {"items": [row(
            prompt="the prompt " + SECRET, messages=[{"content": SECRET}], response={"text": SECRET},
            headers={"Authorization": "Bearer " + SECRET}, header_error_code=SECRET,
        )], "has_more": True, "secret": SECRET}, "summary": {"api_key": SECRET}})
        status, body, text = self.get()
        self.assertEqual(status, 200)
        self.assertTrue(body["truncated"])
        [failure] = body["failures"]
        self.assertEqual(set(failure), FIELDS)
        self.assertNotIn(SECRET, text)

    def test_the_failure_message_never_carries_upstream_text(self):
        for summary in [SUMMARY, "Invalid prompt: send payroll to Alice", "person@example.com " + SECRET,
                        json.dumps({"error": "send payroll to Alice"})]:
            for code, message in [(429, "Rate limited by the provider"), (529, "Provider overloaded"),
                                  (400, "Request rejected by the provider"),
                                  (None, "Request ended without an upstream status")]:
                with self.subTest(summary=summary, code=code):
                    self.manager.reply = (200, page(row(fail_summary=summary, fail_status_code=code)))
                    status, body, text = self.get()
                    self.assertEqual(status, 200)
                    self.assertEqual(body["failures"][0]["message"], message)
                    for leaked in ["prompt", "payroll", "Alice", "person@example.com", SECRET]:
                        self.assertNotIn(leaked, text)

    def test_absent_or_null_optional_fields_are_null(self):
        self.manager.reply = (200, page(
            without("fail_status_code", "stream", "output_tokens", "request_id", "auth_label_snapshot",
                    "auth_index", "source_hash", "auth_provider_snapshot"),
            row(latency_ms=None, fail_status_code=None, stream=None),
            row(model="", auth_provider_snapshot="Not A Provider!", request_id="req 01", latency_ms=-1,
                output_tokens=-1, fail_status_code=-1),
        ))
        status, body, _ = self.get()
        self.assertEqual(status, 200)
        absent, null, unsafe = body["failures"]
        for field in ["status", "streamed", "output_tokens", "request_id", "account", "provider"]:
            self.assertIsNone(absent[field], field)
        for field in ["status", "streamed", "duration_ms"]:
            self.assertIsNone(null[field], field)
        for field in ["model", "provider", "request_id", "duration_ms", "output_tokens", "status"]:
            self.assertIsNone(unsafe[field], field)
        for failure in body["failures"]:
            self.assertEqual((failure["error"], failure["message"]),
                             ("interrupted", "Request ended without an upstream status"))

    def test_account_is_a_label_or_a_stable_hash_never_an_email_or_key(self):
        hashed = "acct-" + hashlib.sha256(b"a1b2c3").hexdigest()[:10]
        for label in ["person@example.com", "codex-person@example.com.json", SECRET, "sk-0123456789abcdefghijk",
                      "1234567890", "", None, {"label": "x"}, "x" * 41, "ka***@example.com"]:
            with self.subTest(label=label):
                self.assertEqual(diagnostics.account(row(auth_label_snapshot=label)), hashed)
        self.assertEqual(diagnostics.account(row(auth_label_snapshot=None, auth_index="")),
                         "acct-" + hashlib.sha256(b"s" * 16).hexdigest()[:10])
        self.assertIsNone(diagnostics.account({"auth_label_snapshot": "person@example.com"}))
        self.assertEqual(diagnostics.account(row(auth_label_snapshot="Team (backup)")), "Team (backup)")

    def test_error_classes_come_from_the_status(self):
        for status, expected in [(429, "rate_limited"), (529, "overloaded"), (500, "server_error"),
                                 (503, "unavailable"), (None, "interrupted"), (0, "interrupted"),
                                 (499, "interrupted"), (502, "server_error"), (401, "unauthorized"),
                                 (418, "client_error")]:
            with self.subTest(status=status):
                self.assertEqual(diagnostics.classify(status), expected)
                failure = diagnostics.fact(row(fail_status_code=status, header_error_kind="overloaded_error"))
                self.assertEqual(failure["error"], expected)

    def test_incompatible_or_missing_manager_is_explicitly_unavailable(self):
        cases = [
            ((404, {"error": "not found"}), "interface_incompatible"),
            ((405, {"error": "method not allowed"}), "interface_incompatible"),
            ((400, {"error": SECRET}), "interface_incompatible"),
            ((200, b"<html>" + SECRET.encode()), "interface_incompatible"),
            ((200, {"items": [row()]}), "interface_incompatible"),
            ((200, {"events": {"rows": [row()], "has_more": False}}), "interface_incompatible"),
            ((200, {"events": {"items": [row()]}}), "interface_incompatible"),
            ((200, page(row(), has_more="false")), "interface_incompatible"),
            ((200, page(row(), has_more=0)), "interface_incompatible"),
            ((200, page(row(), has_more=None)), "interface_incompatible"),
            ((200, page(row(failed=False))), "interface_incompatible"),
            ((200, page(without("failed"))), "interface_incompatible"),
            ((200, page(row(timestamp_ms="2026"))), "interface_incompatible"),
            ((200, page(row(timestamp_ms=float(EVENT_MS)))), "interface_incompatible"),
            ((200, page(row(timestamp_ms=10 ** 18))), "interface_incompatible"),
            ((200, page(row(timestamp_ms=NOW_MS - 24 * 3_600_000 - 1))), "interface_incompatible"),
            ((200, page(row(timestamp_ms=NOW_MS + 1))), "interface_incompatible"),
            ((200, page(*[row()] * (diagnostics.DEFAULT_LIMIT + 1))), "interface_incompatible"),
            ((200, page(row(fail_status_code="529"))), "interface_incompatible"),
            ((200, page(row(fail_status_code=True))), "interface_incompatible"),
            ((200, page(row(fail_status_code=529.0))), "interface_incompatible"),
            ((200, page(without("model"))), "interface_incompatible"),
            ((200, page(row(model=None))), "interface_incompatible"),
            ((200, page(row(model={"nested": SECRET}))), "interface_incompatible"),
            ((200, page(row(latency_ms="1234"))), "interface_incompatible"),
            ((200, page(row(stream="yes"))), "interface_incompatible"),
            ((200, page(row(stream=1))), "interface_incompatible"),
            ((200, page(row(output_tokens="7"))), "interface_incompatible"),
            ((200, page(row(output_tokens=None))), "interface_incompatible"),
            ((200, page(row(request_id={"id": SECRET}))), "interface_incompatible"),
            ((200, page(row(request_id=None))), "interface_incompatible"),
            ((200, page(row(auth_provider_snapshot=["codex", SECRET]))), "interface_incompatible"),
            ((200, page(row(auth_label_snapshot=None))), "interface_incompatible"),
            ((200, page(row(auth_index=5))), "interface_incompatible"),
            ((200, page(row(source_hash=False))), "interface_incompatible"),
            ((200, page(row(), "text")), "interface_incompatible"),
            ((200, []), "interface_incompatible"),
            ((401, {"error": "invalid admin key"}), "manager_unauthorized"),
            ((500, {"error": SECRET}), "manager_error"),
        ]
        for reply, reason in cases:
            with self.subTest(reply=reply):
                self.manager.reply = reply
                status, body, text = self.get()
                self.assertEqual((status, body), (503, {"status": "unavailable", "reason": reason}))
                self.assertNotIn(SECRET, text)

    def test_rows_within_the_requested_window_and_limit_are_compatible(self):
        self.manager.reply = (200, page(row(timestamp_ms=NOW_MS - 3_600_000), row(timestamp_ms=NOW_MS),
                                        has_more=True))
        status, body, _ = self.get(diagnostics.PATH + "?hours=1&limit=2")
        self.assertEqual((status, body["truncated"], len(body["failures"])), (200, True, 2))
        status, body, _ = self.get(diagnostics.PATH + "?hours=1&limit=1")
        self.assertEqual((status, body), (503, {"status": "unavailable", "reason": "interface_incompatible"}))
        self.manager.reply = (200, page())
        self.assertEqual(self.get()[1]["failures"], [])

    def test_unreachable_manager_is_unavailable(self):
        with socket.socket() as unused:
            unused.bind(("127.0.0.1", 0))
            port = unused.getsockname()[1]
        service = diagnostics.Diagnostics([hashlib.sha256(KEY.encode()).hexdigest()], ADMIN,
                                          f"http://127.0.0.1:{port}")
        self.assertEqual(service.answer("GET", diagnostics.PATH, f"Bearer {KEY}"),
                         (503, {"status": "unavailable", "reason": "manager_unreachable"}))

    def test_server_answers_json_and_logs_nothing(self):
        server = diagnostics.serve(self.service, ("127.0.0.1", 0))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = f"http://127.0.0.1:{server.server_address[1]}{diagnostics.PATH}?hours=1"
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            request = urllib.request.Request(url, headers={"Authorization": f"Bearer {KEY}"})
            with urllib.request.urlopen(request, timeout=5) as response:
                self.assertEqual(response.headers["Content-Type"], "application/json")
                self.assertEqual(response.headers["Cache-Control"], "no-store")
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(urllib.request.Request(url, method="POST", data=b"{}"), timeout=5)
            self.assertEqual(error.exception.code, 405)
        self.assertEqual(stderr.getvalue(), "")

    def test_a_client_that_hangs_up_mid_request_leaves_nothing_in_the_log(self):
        server = diagnostics.serve(self.service, ("127.0.0.1", 0))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        # The server closes each connection last, after reporting any error, so this marks a finished request.
        finished = threading.Semaphore(0)
        close = server.shutdown_request

        def closed(request):
            close(request)
            finished.release()

        server.shutdown_request = closed
        self.manager.released.clear()
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            client = socket.create_connection(server.server_address, timeout=5)
            client.sendall(f"GET {diagnostics.PATH} HTTP/1.1\r\nHost: diagnostics\r\n"
                           f"Authorization: Bearer {KEY}\r\n\r\n".encode())
            deadline = time.monotonic() + 5
            while not self.manager.requests and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(self.manager.requests, "the manager query did not start")
            # Without lingering, closing resets the connection while diagnostics still waits for the manager.
            client.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            client.close()
            self.manager.released.set()
            self.assertTrue(finished.acquire(timeout=10))
            request = urllib.request.Request(f"http://127.0.0.1:{server.server_address[1]}{diagnostics.PATH}",
                                             headers={"Authorization": f"Bearer {KEY}"})
            with urllib.request.urlopen(request, timeout=5) as response:
                self.assertEqual((response.status, json.loads(response.read())["status"]), (200, "ok"))
            self.assertTrue(finished.acquire(timeout=10))
        self.assertEqual(stderr.getvalue(), "")

    def test_main_without_keys_stays_off(self):
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            self.assertEqual(diagnostics.main({}), 1)
        self.assertIn("proxy is not affected", stderr.getvalue())


class StartupDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.data = Path(self.directory.name)
        self.runtime = self.data / "runtime"
        self.runtime.mkdir()
        self.key_file = self.runtime / "management-key"
        self.key_file.write_text(ADMIN)

    def prepare(self, **options):
        (self.data / "options.json").write_text(json.dumps(
            {"api_keys": ["client-key"], "management_password": ADMIN, **options}))
        return startup.prepare_diagnostics(self.data, self.key_file)

    def test_off_by_default(self):
        self.assertEqual(self.prepare(), (None, None))
        self.assertEqual(self.prepare(diagnostics_keys=[]), (None, None))
        self.assertFalse((self.runtime / "diagnostics-keys").exists())

    def test_keys_reach_the_sidecar_only_as_digests(self):
        environment, problem = self.prepare(diagnostics_keys=[KEY, KEY, "another-diagnostics-key-1234567"])
        self.assertIsNone(problem)
        keys_file = Path(environment["DIAGNOSTICS_KEYS_FILE"])
        self.assertEqual(json.loads(keys_file.read_text()), sorted(
            hashlib.sha256(key.encode()).hexdigest() for key in [KEY, "another-diagnostics-key-1234567"]))
        self.assertEqual(keys_file.stat().st_mode & 0o777, 0o600)
        self.assertEqual(environment["DIAGNOSTICS_ADMIN_KEY_FILE"], str(self.key_file))
        self.assertNotIn(KEY, json.dumps(environment) + keys_file.read_text())

    def test_invalid_keys_turn_diagnostics_off_without_stopping_startup(self):
        padded = [[padding] for pad in PADDING for key in [KEY, ADMIN, "client-key" * 3]
                  for padding in [pad + key, key + pad, pad + key + pad]]
        for keys in [["short"], [ADMIN], ["client-key" * 3], [KEY, 5], "not-a-list", *padded]:
            with self.subTest(keys=keys):
                (self.data / "options.json").write_text(json.dumps(
                    {"api_keys": ["client-key" * 3], "management_password": ADMIN, "diagnostics_keys": keys}))
                environment, problem = startup.prepare_diagnostics(self.data, self.key_file)
                self.assertIsNone(environment)
                self.assertIn("diagnostics_keys", problem)
                self.assertNotIn(ADMIN, problem)

    def test_keys_the_proxy_or_manager_accept_after_trimming_are_rejected(self):
        for pad in PADDING:
            for options in [{"api_keys": [pad + KEY + pad]}, {"api_keys": ["client-key", KEY + pad]},
                            {"management_password": pad + KEY + pad}]:
                with self.subTest(pad=pad, options=options):
                    self.assertEqual(self.prepare(diagnostics_keys=[KEY], **options),
                                     (None, "diagnostics_keys must differ from api_keys and management_password"))
        environment, problem = self.prepare(diagnostics_keys=[KEY], api_keys=[" client-key-" + KEY])
        self.assertIsNone(problem)
        self.assertIsNotNone(environment)

    def test_proxy_keeps_running_when_diagnostics_exits_or_cannot_start(self):
        started = time.monotonic()
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            status = startup.supervise(
                [([sys.executable, "-c", "import time; time.sleep(1); raise SystemExit(4)"], {})],
                [([sys.executable, "-c", "raise SystemExit(2)"], {}), ([str(self.data / "missing")], {})])
        # Only the required process's own exit ends supervision.
        self.assertEqual(status, 4)
        self.assertGreaterEqual(time.monotonic() - started, 1)
        self.assertIn("Diagnostics stopped; the proxy keeps running.", stderr.getvalue())
        self.assertIn("Diagnostics could not start; the proxy keeps running.", stderr.getvalue())

    def test_a_running_diagnostics_process_stops_with_the_app(self):
        status = startup.supervise([([sys.executable, "-c", "raise SystemExit(3)"], {})],
                                   [([sys.executable, "-c", "import time; time.sleep(60)"], {})])
        self.assertEqual(status, 3)


if __name__ == "__main__":
    unittest.main()
