import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

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
            "cooldown": {"disable-cooling": False},
        })

    def test_each_routing_option_overrides_its_default(self):
        cases = [
            ("routing_strategy", "fill-first", ["strategy"], "fill-first"),
            ("routing_strategy", "weighted-round-robin", ["strategy"], "weighted-round-robin"),
            ("session_affinity", False, ["session-affinity"], False),
            ("session_affinity_ttl", "2h30m", ["session-affinity-ttl"], "2h30m"),
            ("auto_switch_accounts", False, ["retry", "request-retry"], 0),
            ("auto_switch_accounts", False, ["retry", "max-retry-credentials"], 1),
            ("auto_switch_accounts", False, ["cooldown", "disable-cooling"], True),
        ]
        for option, value, path, expected in cases:
            with self.subTest(option=option, path=path):
                (self.data / "options.json").write_text(json.dumps({**self.options, option: value}))
                routing = json.loads(startup.prepare(self.data).read_text())["routing"]
                for key in path:
                    routing = routing[key]
                self.assertEqual(routing, expected)

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
            "cooldown": {"disable-cooling": False, "save-cooldown-status": True},
        })

    def test_empty_routing_section_gets_defaults(self):
        startup.prepare(self.data).write_text("routing:\n")
        routing = json.loads(startup.prepare(self.data).read_text())["routing"]
        self.assertEqual(routing["session-affinity-ttl"], "1h")

    def test_invalid_options_do_not_overwrite_existing_config(self):
        config = startup.prepare(self.data)
        original = config.read_bytes()
        for field, value in [("api_keys", []), ("api_keys", [""]), ("api_keys", [1]), ("management_password", "short"), ("logging", "false"),
                             ("routing_strategy", "random"), ("session_affinity", "true"), ("auto_switch_accounts", 1),
                             ("session_affinity_ttl", ""), ("session_affinity_ttl", "0h"), ("session_affinity_ttl", "1 hour"),
                             ("session_affinity_ttl", "-1h"), ("session_affinity_ttl", 3600)]:
            with self.subTest(field=field, value=value):
                options = dict(self.options)
                options[field] = value
                (self.data / "options.json").write_text(json.dumps(options))
                with self.assertRaises(ValueError):
                    startup.prepare(self.data)
                self.assertEqual(config.read_bytes(), original)

if __name__ == "__main__":
    unittest.main()
