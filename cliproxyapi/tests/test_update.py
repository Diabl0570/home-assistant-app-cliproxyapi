import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('updater', Path(__file__).parents[2] / 'scripts/update_upstream.py')
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)

class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        app = self.root / 'cliproxyapi'
        app.mkdir()
        self.manifest = app / 'updater.json'
        self.manifest.write_text(json.dumps({'repository': 'router-for-me/CLIProxyAPI', 'version': '8.0.4', 'asset': 'old', 'sha256': 'old'}))
        (app / 'config.yaml').write_text('version: "8.0.4-1"\n')
        (app / 'CHANGELOG.md').write_text('# 8.0.4-1\n')
        self.release = {'tag_name': 'v8.0.5', 'draft': False, 'prerelease': False, 'assets': [{'name':'CLIProxyAPI_8.0.5_linux_amd64.tar.gz', 'browser_download_url':'https://asset'}, {'name':'checksums.txt', 'browser_download_url':'https://checksums'}]}

    def run_update(self, checksum=None):
        def fetch(url):
            if url.endswith('/releases/latest'):
                return json.dumps(self.release).encode()
            return (checksum or ('a'*64 + '  CLIProxyAPI_8.0.5_linux_amd64.tar.gz\n')).encode()
        with patch.object(updater, 'ROOT', self.root), patch.object(updater, 'MANIFEST', self.manifest), patch.object(updater, 'fetch', fetch):
            updater.main()

    def test_update_changes_all_release_metadata(self):
        self.run_update()
        self.assertEqual(json.loads(self.manifest.read_text())['sha256'], 'a'*64)
        self.assertIn('version: "8.0.5-1"', (self.root / 'cliproxyapi/config.yaml').read_text())
        self.assertIn('# 8.0.5-1', (self.root / 'cliproxyapi/CHANGELOG.md').read_text())

    def test_same_version_is_noop(self):
        original = self.manifest.read_text()
        self.release['tag_name'] = 'v8.0.4'
        self.run_update()
        self.assertEqual(self.manifest.read_text(), original)

    def test_prerelease_is_refused(self):
        self.release['prerelease'] = True
        with self.assertRaises(SystemExit):
            self.run_update()

    def test_major_release_and_missing_checksum_do_not_modify_pin(self):
        original = self.manifest.read_text()
        self.release['tag_name'] = 'v9.0.0'
        with self.assertRaises(SystemExit):
            self.run_update()
        self.release['tag_name'] = 'v8.0.5'
        with self.assertRaises(SystemExit):
            self.run_update('invalid checksum')
        self.assertEqual(self.manifest.read_text(), original)
