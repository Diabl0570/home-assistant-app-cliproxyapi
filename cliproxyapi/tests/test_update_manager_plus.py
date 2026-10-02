import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import yaml

spec = importlib.util.spec_from_file_location('manager_updater', Path(__file__).parents[2] / 'scripts/update_manager_plus.py')
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)

ASSET = 'cpa-manager-plus_v1.15.0_linux_amd64.tar.gz'

class ManagerPlusUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        app = self.root / 'cliproxyapi'
        app.mkdir()
        self.manifest = app / 'manager-plus.json'
        self.manifest.write_text(json.dumps({'repository': 'seakee/CPA-Manager-Plus', 'version': '1.14.2', 'asset': 'old', 'sha256': 'old'}))
        (app / 'updater.json').write_text(json.dumps({'version': '8.0.4'}))
        (app / 'config.yaml').write_text('name: CLIProxyAPI\nversion: "8.0.4-3"\n')
        (app / 'CHANGELOG.md').write_text('# 8.0.4-3\n')
        self.release = {'tag_name': 'v1.15.0', 'draft': False, 'prerelease': False, 'assets': [
            {'name': ASSET, 'browser_download_url': 'https://asset'},
            {'name': 'checksums.txt', 'browser_download_url': 'https://checksums'},
            {'name': 'release-info.json', 'browser_download_url': 'https://info'}]}
        self.info = {'release': {'stage': 'stable'}, 'update': {'breaking': False, 'migration_required': False, 'minimum_direct_upgrade_version': None}, 'compatibility': {'minimum_cpa_version': 'v7.3.4'}}
        self.checksums = 'a' * 64 + '  ./' + ASSET + '\n'

    def run_update(self):
        def fetch(url):
            if url.endswith('/releases/latest'):
                return json.dumps(self.release).encode()
            if url == 'https://info':
                return json.dumps(self.info).encode()
            return self.checksums.encode()
        with patch.object(updater, 'ROOT', self.root), patch.object(updater, 'MANIFEST', self.manifest), patch.object(updater, 'fetch', fetch):
            updater.main()

    def app_version(self):
        return yaml.safe_load((self.root / 'cliproxyapi/config.yaml').read_text())['version']

    def assert_refused_without_changes(self):
        original = self.manifest.read_text()
        with self.assertRaises(SystemExit):
            self.run_update()
        self.assertEqual(self.manifest.read_text(), original)
        self.assertEqual(self.app_version(), '8.0.4-3')

    def test_update_changes_pin_and_bumps_app_suffix(self):
        self.run_update()
        manifest = json.loads(self.manifest.read_text())
        self.assertEqual((manifest['version'], manifest['asset'], manifest['sha256']), ('1.15.0', ASSET, 'a' * 64))
        self.assertEqual(self.app_version(), '8.0.4-4')
        changelog = (self.root / 'cliproxyapi/CHANGELOG.md').read_text()
        self.assertTrue(changelog.startswith('# 8.0.4-4\n\n- Update CPA Manager Plus to 1.15.0'))

    def test_same_version_is_noop(self):
        original = self.manifest.read_text()
        self.release['tag_name'] = 'v1.14.2'
        self.run_update()
        self.assertEqual(self.manifest.read_text(), original)

    def test_prerelease_and_major_release_are_refused(self):
        self.release['prerelease'] = True
        self.assert_refused_without_changes()
        self.release['prerelease'] = False
        self.release['tag_name'] = 'v2.0.0'
        self.assert_refused_without_changes()

    def test_breaking_or_incompatible_release_is_refused(self):
        for section, field, value in [('update', 'breaking', True), ('update', 'migration_required', True),
                                      ('update', 'minimum_direct_upgrade_version', 'v1.14.3'),
                                      ('compatibility', 'minimum_cpa_version', 'v8.1.0'), ('release', 'stage', 'rc')]:
            with self.subTest(field=field):
                original = self.info[section][field]
                self.info[section][field] = value
                self.assert_refused_without_changes()
                self.info[section][field] = original

    def test_missing_checksum_is_refused(self):
        self.checksums = 'invalid checksum'
        self.assert_refused_without_changes()

if __name__ == '__main__':
    unittest.main()
