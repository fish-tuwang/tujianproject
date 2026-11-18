"""Install a launchd updater for the existing Mac Docker deployment (Python 3.10+)."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import time
import urllib.request

REPOSITORY = 'https://github.com/fish-tuwang/tujianproject.git'
BASELINE = '288b33d'
HOME = Path.home()
STATE = HOME / 'Library/Application Support/LittleAtlasUpdater'
LABEL = 'com.little-atlas.updater'
BLOCKED = ('backend/migrations/', 'Dockerfile', 'requirements.lock', 'pyproject.toml', 'compose.', '.env')


def log(message):
    print(time.strftime('%Y-%m-%d %H:%M:%S') + ' ' + message, flush=True)


def run(args, cwd=None, timeout=900, capture=False):
    return subprocess.run(args, cwd=cwd, check=True, timeout=timeout,
                          stdout=subprocess.PIPE if capture else None,
                          stderr=subprocess.PIPE if capture else None).stdout


def compose(root, *args):
    return run(['docker', 'compose', '--env-file', '.env.mac', '-p', 'little-atlas-mac',
                '-f', 'compose.mac.yaml', *args], cwd=root)


def healthy(timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen('http://127.0.0.1:8092/health/ready', timeout=5) as response:
                if response.status == 200 and json.load(response).get('status') == 'ready':
                    return
        except (OSError, ValueError):
            pass
        time.sleep(2)
    raise RuntimeError('Mac API readiness check failed')


def save_revision(path, revision):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(revision + '\n')
    temporary.replace(path)


def update(root, state):
    root = root.resolve()
    for name in ['compose.mac.yaml', '.env.mac', 'backend/preview/app.js']:
        if not (root / name).is_file():
            raise RuntimeError('Missing project file: ' + name)
    repo = state / 'upstream.git'
    if not repo.exists():
        run(['git', 'init', '--bare', str(repo)])
    git = ['git', '--git-dir=' + str(repo)]
    run(git + ['fetch', '--quiet', REPOSITORY, 'main'])
    target = run(git + ['rev-parse', 'FETCH_HEAD'], capture=True).decode().strip()
    revision_file = state / 'revision'
    previous = revision_file.read_text().strip() if revision_file.exists() else BASELINE
    previous = run(git + ['rev-parse', previous + '^{commit}'], capture=True).decode().strip()
    if target == previous:
        log('UP_TO_DATE ' + target[:12]); return
    run(git + ['merge-base', '--is-ancestor', previous, target])
    changed = run(git + ['diff', '--name-only', '-z', previous, target], capture=True).decode().split('\0')
    blocked = [name for name in changed if name and name.startswith(BLOCKED)]
    if blocked:
        raise RuntimeError('Manual deployment required for schema/build configuration changes: ' + ', '.join(blocked))
    names = [name for name in changed if name.startswith('backend/')]
    if not names:
        save_revision(revision_file, target)
        log('NO_RUNTIME_CHANGES ' + target[:12]); return
    for name in names:
        if not (root / name).resolve().is_relative_to(root):
            raise RuntimeError('Unsafe source path')
    patch = run(git + ['diff', '--binary', '--full-index', '--no-ext-diff', previous, target, '--', 'backend/'], capture=True)
    patch_path = state / 'pending.patch'
    patch_path.write_bytes(patch)
    apply = ['git', '--git-dir=' + str(repo), '--work-tree=' + str(root), '-c', 'core.bare=false', 'apply']
    run(apply + ['--check', str(patch_path)], cwd=root)
    healthy(timeout=15)
    details = json.loads(run(['docker', 'inspect', 'little-atlas-mac-api-1'], capture=True))[0]
    old_image, image_tag = details['Image'], details['Config']['Image']
    if ':' not in image_tag.rsplit('/', 1)[-1]:
        image_tag += ':latest'
    if '@' in image_tag or image_tag.startswith('sha256:'):
        raise RuntimeError('API image must use a mutable build tag for rollback')
    backup = state / 'backups' / (time.strftime('%Y%m%d-%H%M%S') + '-' + target[:8])
    backup.mkdir(parents=True)
    manifest = {}
    for name in names:
        source = root / name
        if source.exists():
            if not source.is_file() or source.is_symlink():
                raise RuntimeError('Only regular source files can be updated: ' + name)
            destination = backup / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            manifest[name] = True
        else:
            manifest[name] = False
    (backup / 'manifest.json').write_text(json.dumps({'files': manifest, 'old_image': old_image, 'target': target}, indent=2))
    switched = False
    try:
        run(apply + [str(patch_path)], cwd=root)
        compose(root, 'build', 'api')
        switched = True
        compose(root, 'up', '-d', '--no-deps', '--no-build', 'api')
        healthy()
        expected = hashlib.sha256((root / 'backend/preview/app.js').read_bytes()).hexdigest()
        actual = run(['docker', 'exec', 'little-atlas-mac-api-1', 'python', '-c',
                      "import hashlib;print(hashlib.sha256(open('/app/backend/preview/app.js','rb').read()).hexdigest())"], capture=True).decode().strip()
        if actual != expected:
            raise RuntimeError('Running container does not contain the updated UI')
        save_revision(revision_file, target)
        log('UPDATE_OK ' + target[:12] + ' readiness=200 ui_sha256=' + expected + ' backup=' + str(backup))
    except BaseException:
        for name, existed in manifest.items():
            source = root / name
            if existed:
                shutil.copy2(backup / name, source)
            elif source.exists():
                source.unlink()
        run(['docker', 'image', 'tag', old_image, image_tag])
        if switched:
            compose(root, 'up', '-d', '--no-deps', '--no-build', 'api')
            healthy()
        log('ROLLED_BACK source and API image; database and volumes unchanged')
        raise


def install(root):
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination = STATE / 'updater.py'
    if Path(__file__).resolve() != destination:
        shutil.copy2(__file__, destination)
    config = STATE / 'config.json'
    config.write_text(json.dumps({'project': str(root.resolve())}))
    plist = HOME / 'Library/LaunchAgents' / (LABEL + '.plist')
    plist.parent.mkdir(parents=True, exist_ok=True)
    path = '/opt/homebrew/bin:/usr/local/bin:/Applications/Docker.app/Contents/Resources/bin:/usr/bin:/bin:/usr/sbin:/sbin'
    settings = {'Label': LABEL, 'ProgramArguments': [sys.executable, str(destination)],
                'StartInterval': 300, 'RunAtLoad': True,
                'EnvironmentVariables': {'PATH': path, 'GIT_TERMINAL_PROMPT': '0'},
                'StandardOutPath': str(STATE / 'updates.log'), 'StandardErrorPath': str(STATE / 'errors.log')}
    plist.write_bytes(plistlib.dumps(settings))
    os.environ['PATH'] = path + ':' + os.environ.get('PATH', '')
    os.environ['GIT_TERMINAL_PROMPT'] = '0'
    # First deployment must succeed before enabling unattended updates.
    with (STATE / 'lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        update(root, STATE)
    subprocess.run(['launchctl', 'bootout', 'gui/' + str(os.getuid()), str(plist)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    run(['launchctl', 'bootstrap', 'gui/' + str(os.getuid()), str(plist)])
    log('INSTALLED checks GitHub main every 5 minutes while this Mac user is logged in')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install', type=Path)
    args = parser.parse_args()
    if args.install:
        install(args.install); return
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (STATE / 'lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log('SKIP another update is running'); return
        config = json.loads((STATE / 'config.json').read_text())
        for name in ['updates.log', 'errors.log']:
            logfile = STATE / name
            if logfile.exists() and logfile.stat().st_size > 5 * 1024 * 1024:
                logfile.replace(STATE / (name + '.previous'))
        update(Path(config['project']), STATE)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        log('UPDATE_FAILED ' + type(error).__name__ + ': ' + str(error))
        sys.exit(1)
