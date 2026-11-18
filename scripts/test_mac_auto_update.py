"""Exercise real Git patches with simulated Docker operations; no production changes."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

if sys.platform == 'win32':
    sys.modules['fcntl'] = types.SimpleNamespace()
spec = importlib.util.spec_from_file_location('mac_updater', Path(__file__).with_name('mac_auto_update.py'))
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.upstream = self.base / 'origin'
        self.root = self.base / 'mac'
        self.state = self.base / 'state'
        for directory in [self.upstream, self.root, self.state]:
            directory.mkdir()
        def git(*args):
            return subprocess.check_output(['git', '-C', str(self.upstream), *args], stderr=subprocess.DEVNULL).decode().strip()
        self.git = git
        git('init', '-b', 'main')
        git('config', 'user.name', 'Updater Test')
        git('config', 'user.email', 'test@example.invalid')
        for directory in [self.upstream, self.root]:
            (directory / 'backend/preview').mkdir(parents=True)
            (directory / 'backend/preview/app.js').write_text('const year = 2008;\n')
        (self.root / '.env.mac').write_text('PRIVATE_KEEP=yes\n')
        (self.root / 'compose.mac.yaml').write_text('MAC_KEEP\n')
        git('add', '.'); git('commit', '-m', 'baseline')
        self.baseline = git('rev-parse', 'HEAD')
        (self.upstream / 'backend/preview/app.js').write_text('const year = 2026;\n')
        git('commit', '-am', 'year index')
        self.target = git('rev-parse', 'HEAD')
        self.commands = []
        self.real_run = updater.run
        self.docker = []

    def execute(self, failure=None):
        def run(args, **kwargs):
            if args[0] != 'docker':
                return self.real_run(args, **kwargs)
            self.docker.append(args)
            if args[1] == 'inspect':
                return json.dumps([{'Image': 'sha256:old', 'Config': {'Image': 'little-atlas-mac-api'}}]).encode()
            if args[1] == 'exec':
                import hashlib
                return hashlib.sha256((self.root / 'backend/preview/app.js').read_bytes()).hexdigest().encode()
            return b''
        def compose(root, *args):
            self.commands.append(args)
            if failure == 'build' and args[0] == 'build':
                raise RuntimeError('simulated build failure')
        health_calls = []
        def health(**kwargs):
            health_calls.append(kwargs)
            if failure == 'health' and len(health_calls) == 2:
                raise RuntimeError('simulated readiness failure')
        with patch.object(updater, 'REPOSITORY', str(self.upstream)), patch.object(updater, 'BASELINE', self.baseline), patch.object(updater, 'run', side_effect=run), patch.object(updater, 'compose', side_effect=compose), patch.object(updater, 'healthy', side_effect=health):
            updater.update(self.root, self.state)

    def test_success_and_repeat(self):
        self.execute()
        self.assertEqual((self.root / 'backend/preview/app.js').read_text(), 'const year = 2026;\n')
        self.assertEqual((self.state / 'revision').read_text().strip(), self.target)
        self.assertEqual((self.root / '.env.mac').read_text(), 'PRIVATE_KEEP=yes\n')
        self.assertEqual((self.root / 'compose.mac.yaml').read_text(), 'MAC_KEEP\n')
        self.assertEqual(self.commands, [('build', 'api'), ('up', '-d', '--no-deps', '--no-build', 'api')])
        self.commands.clear()
        self.execute()
        self.assertEqual(self.commands, [])

    def test_conflict_keeps_custom_source(self):
        source = self.root / 'backend/preview/app.js'
        source.write_text('Mac custom code\n')
        with self.assertRaises(subprocess.CalledProcessError):
            self.execute()
        self.assertEqual(source.read_text(), 'Mac custom code\n')
        self.assertEqual(self.commands, [])
        self.assertFalse((self.state / 'revision').exists())

    def test_build_failure_restores_source_without_restarting(self):
        with self.assertRaises(RuntimeError):
            self.execute('build')
        self.assertEqual((self.root / 'backend/preview/app.js').read_text(), 'const year = 2008;\n')
        self.assertEqual(self.commands, [('build', 'api')])
        self.assertFalse((self.state / 'revision').exists())
        self.assertIn(['docker', 'image', 'tag', 'sha256:old', 'little-atlas-mac-api:latest'], self.docker)

    def test_health_failure_restores_image_and_restarts_old_api(self):
        with self.assertRaises(RuntimeError):
            self.execute('health')
        self.assertEqual((self.root / 'backend/preview/app.js').read_text(), 'const year = 2008;\n')
        self.assertEqual(sum(c[0] == 'up' for c in self.commands), 2)
        self.assertFalse((self.state / 'revision').exists())

    def test_migration_blocks_deployment(self):
        directory = self.upstream / 'backend/migrations'
        directory.mkdir()
        (directory / 'new.py').write_text('# migration\n')
        self.git('add', '.'); self.git('commit', '-m', 'migration')
        with self.assertRaisesRegex(RuntimeError, 'Manual deployment required'):
            self.execute()
        self.assertEqual(self.commands, [])
        self.assertEqual((self.root / 'backend/preview/app.js').read_text(), 'const year = 2008;\n')


if __name__ == '__main__':
    unittest.main(verbosity=2)
