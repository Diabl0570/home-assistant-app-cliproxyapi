from contextlib import redirect_stderr
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("startup", Path(__file__).parents[1] / "run.py")
startup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(startup)

class StartupTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.data = Path(self.directory.name)
        self.options = {"api_keys": ['key: # "\n☃'], "management_password": "a-separate-random-password-12345", "logging": False}
        self.write_options()

    def write_options(self):
        (self.data / "options.json").write_text(json.dumps(self.options))

    def test_strings_are_data_and_files_are_private(self):
        config = startup.prepare(self.data)
        saved = json.loads(config.read_text())
        self.assertEqual(saved["access"]["api-keys"], self.options["api_keys"])
        self.assertEqual(config.stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.data / "auths").stat().st_mode & 0o777, 0o700)

    def test_panel_yaml_and_auth_survive_restart(self):
        config = startup.prepare(self.data)
        config.write_text("api-keys:\n  codex:\n    - name: personal\n      keys:\n        - api-key: provider-secret\noauth:\n  model-alias:\n    codex: []\nserver:\n  port: 9999\n")
        credential = self.data / "auths" / "account.json"
        credential.write_text('{"type":"codex"}')
        saved = json.loads(startup.prepare(self.data).read_text())
        self.assertEqual(saved["api-keys"]["codex"][0]["keys"][0]["api-key"], "provider-secret")
        self.assertEqual(saved["oauth"]["model-alias"], {"codex": []})
        self.assertEqual(saved["server"]["port"], 8317)
        self.assertEqual(credential.read_text(), '{"type":"codex"}')
        self.assertEqual(credential.stat().st_mode & 0o777, 0o600)

    def test_routing_defaults_apply_without_routing_options(self):
        saved = json.loads(startup.prepare(self.data).read_text())
        self.assertEqual(saved["routing"], {
            "strategy": "round-robin", "session-affinity": True, "session-affinity-ttl": "1h",
            "retry": {"request-retry": 3, "max-retry-credentials": 0},
        })

    def test_each_routing_option_overrides_its_default(self):
        cases = [
            ("routing_strategy", "fill-first", ["strategy"], "fill-first"),
            ("session_affinity", False, ["session-affinity"], False),
            ("session_affinity_ttl", "2h30m", ["session-affinity-ttl"], "2h30m"),
        ]
        for option, value, path, expected in cases:
            with self.subTest(option=option, path=path):
                (self.data / "options.json").write_text(json.dumps({**self.options, option: value}))
                routing = json.loads(startup.prepare(self.data).read_text())["routing"]
                for key in path:
                    routing = routing[key]
                self.assertEqual(routing, expected)

    def test_retry_other_accounts_sets_only_request_retry_fields(self):
        for value, retry in [(True, {"request-retry": 3, "max-retry-credentials": 0}),
                             (False, {"request-retry": 0, "max-retry-credentials": 1})]:
            with self.subTest(value=value):
                (self.data / "options.json").write_text(json.dumps({**self.options, "retry_other_accounts": value}))
                routing = json.loads(startup.prepare(self.data).read_text())["routing"]
                self.assertEqual(routing, {"strategy": "round-robin", "session-affinity": True,
                                           "session-affinity-ttl": "1h", "retry": retry})

    def test_routing_options_replace_existing_routing_values(self):
        config = startup.prepare(self.data)
        config.write_text("routing:\n  strategy: fill-first\n  session-affinity: false\n  session-affinity-ttl: 5m\n"
                          "  session-affinity-subagents: false\n  retry:\n    request-retry: 0\n    max-retry-credentials: 1\n"
                          "    max-retry-interval: 30\n  cooldown:\n    disable-cooling: true\n    save-cooldown-status: true\n")
        routing = json.loads(startup.prepare(self.data).read_text())["routing"]
        self.assertEqual(routing, {
            "strategy": "round-robin", "session-affinity": True, "session-affinity-ttl": "1h",
            "session-affinity-subagents": False,
            "retry": {"request-retry": 3, "max-retry-credentials": 0, "max-retry-interval": 30},
            "cooldown": {"disable-cooling": True, "save-cooldown-status": True},
        })

    def test_empty_routing_section_gets_defaults(self):
        startup.prepare(self.data).write_text("routing:\n")
        routing = json.loads(startup.prepare(self.data).read_text())["routing"]
        self.assertEqual(routing["session-affinity-ttl"], "1h")

    def test_blocked_models_default_covers_every_credential_type(self):
        config = startup.prepare(self.data)
        config.write_text("api-keys:\n  codex:\n    - name: personal\n      keys:\n        - api-key: one\n"
                          "        - api-key: two\n          excluded-models: []\n"
                          "codex-api-key:\n  - api-key: legacy\n")
        saved = json.loads(startup.prepare(self.data).read_text())
        blocked = ["gpt-6-sol", "gpt-5.6-sol"]
        oauth = saved["oauth"]["excluded-models"]
        self.assertEqual(oauth["codex"], blocked)
        self.assertEqual(set(oauth), set(startup.OAUTH_PROVIDERS))
        self.assertTrue(all(models == blocked for models in oauth.values()))
        group = saved["api-keys"]["codex"][0]
        self.assertEqual(group["excluded-models"], blocked)
        self.assertNotIn("excluded-models", group["keys"][0])
        self.assertEqual(group["keys"][1]["excluded-models"], blocked)
        self.assertEqual(saved["codex-api-key"][0]["excluded-models"], blocked)
        self.assertEqual(json.loads((self.data / "blocked-models.json").read_text()), blocked)

    def test_blocked_models_option_replaces_the_default(self):
        startup.prepare(self.data)
        (self.data / "options.json").write_text(json.dumps({**self.options, "blocked_models": [" GPT-6-Sol ", "gpt-6-sol", "o3"]}))
        saved = json.loads(startup.prepare(self.data).read_text())
        self.assertEqual(saved["oauth"]["excluded-models"]["codex"], ["gpt-6-sol", "o3"])

    def test_empty_blocked_models_blocks_nothing(self):
        (self.data / "options.json").write_text(json.dumps({**self.options, "blocked_models": []}))
        saved = json.loads(startup.prepare(self.data).read_text())
        self.assertNotIn("excluded-models", saved["oauth"])
        startup.prepare(self.data)
        (self.data / "options.json").write_text(json.dumps(self.options))
        startup.prepare(self.data)
        (self.data / "options.json").write_text(json.dumps({**self.options, "blocked_models": []}))
        saved = json.loads(startup.prepare(self.data).read_text())
        self.assertEqual(saved["oauth"]["excluded-models"]["codex"], [])

    def test_blocked_models_keep_existing_exclusions(self):
        config = startup.prepare(self.data)
        config.write_text("oauth-excluded-models:\n  codex: [gpt-5-codex-mini, gpt-6-sol]\n  plugin: ['x-*']\n"
                          "api-keys:\n  claude:\n    - name: work\n      excluded-models: ['*']\n      keys:\n        - api-key: k\n")
        saved = json.loads(startup.prepare(self.data).read_text())
        self.assertNotIn("oauth-excluded-models", saved)
        oauth = saved["oauth"]["excluded-models"]
        self.assertEqual(oauth["codex"], ["gpt-5-codex-mini", "gpt-6-sol", "gpt-5.6-sol"])
        self.assertEqual(oauth["plugin"], ["x-*", "gpt-6-sol", "gpt-5.6-sol"])
        self.assertEqual(saved["api-keys"]["claude"][0]["excluded-models"], ["*", "gpt-6-sol", "gpt-5.6-sol"])
        # Unblocking removes only what the app added, including a model the user had also excluded.
        (self.data / "options.json").write_text(json.dumps({**self.options, "blocked_models": ["gpt-5.6-sol"]}))
        saved = json.loads(startup.prepare(self.data).read_text())
        self.assertEqual(saved["oauth"]["excluded-models"]["codex"], ["gpt-5-codex-mini", "gpt-5.6-sol"])
        self.assertEqual(saved["api-keys"]["claude"][0]["excluded-models"], ["*", "gpt-5.6-sol"])

    def test_invalid_options_do_not_overwrite_existing_config(self):
        config = startup.prepare(self.data)
        original = config.read_bytes()
        for field, value in [("api_keys", []), ("api_keys", [""]), ("api_keys", [1]), ("management_password", "short"),
                             ("management_password", " leading-space-password-12345"),
                             ("management_password", "trailing-space-password-12345\n"), ("logging", "false"),
                             ("routing_strategy", "random"), ("routing_strategy", "weighted-round-robin"),
                             ("session_affinity", "true"), ("retry_other_accounts", 1),
                             ("session_affinity_ttl", ""), ("session_affinity_ttl", "0h"), ("session_affinity_ttl", "1 hour"),
                             ("session_affinity_ttl", "-1h"), ("session_affinity_ttl", 3600),
                             ("blocked_models", "gpt-6-sol"), ("blocked_models", [""]), ("blocked_models", [1])]:
            with self.subTest(field=field, value=value):
                options = dict(self.options)
                options[field] = value
                (self.data / "options.json").write_text(json.dumps(options))
                with self.assertRaises(ValueError):
                    startup.prepare(self.data)
                self.assertEqual(config.read_bytes(), original)

    def test_usage_statistics_default_on_but_panel_choice_survives(self):
        config = startup.prepare(self.data)
        self.assertTrue(json.loads(config.read_text())["observability"]["usage"]["usage-statistics-enabled"])
        config.write_text('{"observability": {"usage": {"usage-statistics-enabled": false}}}')
        saved = json.loads(startup.prepare(self.data).read_text())
        self.assertFalse(saved["observability"]["usage"]["usage-statistics-enabled"])

    def test_manager_uses_management_password_without_exposing_it(self):
        startup.prepare(self.data)
        runtime = self.data / "runtime"
        runtime.mkdir()
        environment, key_file = startup.prepare_manager(self.data, runtime)
        password = self.options["management_password"]
        self.assertEqual(key_file.read_text(), password)
        self.assertEqual(key_file.stat().st_mode & 0o777, 0o600)
        self.assertEqual(runtime.stat().st_mode & 0o777, 0o700)
        self.assertNotIn(password, json.dumps(environment))
        self.assertEqual(environment["CPA_MANAGEMENT_KEY_FILE"], str(key_file))
        self.assertEqual(environment["CPA_MANAGER_ADMIN_KEY_FILE"], str(key_file))
        self.assertEqual(environment["CPA_UPSTREAM_URL"], "http://127.0.0.1:8317")
        self.assertEqual(environment["USAGE_DB_PATH"], str(self.data / "cpa-manager-plus" / "usage.sqlite"))
        self.assertEqual((self.data / "cpa-manager-plus").stat().st_mode & 0o777, 0o700)

    def test_admin_key_sync_skips_first_start_and_resets_existing_database(self):
        startup.prepare(self.data)
        runtime = self.data / "runtime"
        runtime.mkdir()
        environment, key_file = startup.prepare_manager(self.data, runtime)
        record = self.data / "calls"
        binary = self.data / "fake-manager"
        binary.write_text(f"#!{sys.executable}\nimport sys\nopen({str(record)!r}, 'a').write(' '.join(sys.argv[1:]) + '\\n')\n")
        binary.chmod(0o700)
        self.assertTrue(startup.sync_admin_key(str(binary), environment, key_file))
        self.assertFalse(record.exists())
        Path(environment["USAGE_DB_PATH"]).write_text("database")
        self.assertTrue(startup.sync_admin_key(str(binary), environment, key_file))
        self.assertEqual(record.read_text().split(), ["reset-admin-key", "--db-path", environment["USAGE_DB_PATH"],
                                                      "--admin-key-file", str(key_file)])

    def test_failed_admin_key_reset_stops_startup_before_any_launch(self):
        record = self.data / "calls"
        def fake(name, code):
            binary = self.data / name
            binary.write_text(f"#!{sys.executable}\nimport sys\nopen({str(record)!r}, 'a').write({name!r} + ' ' + ' '.join(sys.argv[1:]) + '\\n')\nsys.exit({code})\n")
            binary.chmod(0o700)
            return str(binary)
        (self.data / "cpa-manager-plus").mkdir()
        (self.data / "cpa-manager-plus" / "usage.sqlite").write_text("database")
        stderr = io.StringIO()
        with patch.object(tempfile, "tempdir", self.directory.name), redirect_stderr(stderr):
            status = startup.main(self.data, proxy=fake("proxy", 0), manager=fake("manager", 1))
        self.assertEqual(status, 1)
        self.assertIn("admin key could not be reset", stderr.getvalue())
        self.assertNotIn(self.options["management_password"], stderr.getvalue())
        calls = record.read_text().splitlines()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].split()[:2], ["manager", "reset-admin-key"])

    def test_supervisor_stops_remaining_process_when_one_exits(self):
        status = startup.supervise([([sys.executable, "-c", "import time; time.sleep(60)"], {}),
                                    ([sys.executable, "-c", "raise SystemExit(3)"], {})])
        self.assertEqual(status, 3)

    def test_malformed_exclusions_do_not_overwrite_existing_config(self):
        config = startup.prepare(self.data)
        for text in ["oauth:\n  excluded-models: [gpt-6-sol]\n", "oauth:\n  excluded-models:\n    codex: gpt-6-sol\n",
                     "api-keys:\n  codex: {}\n", "codex-api-key:\n  - excluded-models: [1]\n"]:
            with self.subTest(text=text):
                config.write_text(text)
                with self.assertRaises(ValueError):
                    startup.prepare(self.data)
                self.assertEqual(config.read_text(), text)

if __name__ == "__main__":
    unittest.main()
