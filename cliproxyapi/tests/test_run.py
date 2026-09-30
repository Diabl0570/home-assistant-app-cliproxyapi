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

    def test_invalid_options_do_not_overwrite_existing_config(self):
        config = startup.prepare(self.data)
        original = config.read_bytes()
        for field, value in [("api_keys", []), ("api_keys", [""]), ("api_keys", [1]), ("management_password", "short"), ("logging", "false")]:
            with self.subTest(field=field, value=value):
                options = dict(self.options)
                options[field] = value
                (self.data / "options.json").write_text(json.dumps(options))
                with self.assertRaises(ValueError):
                    startup.prepare(self.data)
                self.assertEqual(config.read_bytes(), original)

if __name__ == "__main__":
    unittest.main()
