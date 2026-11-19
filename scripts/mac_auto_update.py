"""Install a launchd updater for the existing Mac Docker deployment (Python 3.10+)."""
import argparse
import ast
import tempfile
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



# Only the two diagnosed releases have structural conflict resolution. Other
# overlapping edits still stop before changing the project.
KNOWN_CONFLICTS = {
    'backend/app/gunpla.py': (
        '432de7d18e705e72d56d1dae849d4454b804badbb89a303095cb5dd10048c0e0',
        'cf80d233b2ad8d02cb87a4494dee55f46c6f387c4b2d7d7f96fc34ec1448482e'),
    'backend/preview/theme.css': (
        'a178bc3c14d400b84cd3a32b417d3f34c2bdd353372e47af694fc245c7e3f6df',
        '49c5209d0b3216c2ee4b85f83e82c3f00dd5524986a56cb2dc36971b610c9516'),
}


def repair_gunpla(local):
    """Change only classification expressions, preserving Mac Dalong methods."""
    source = local.decode('utf-8-sig').replace('\r\n', '\n')
    tree = ast.parse(source)
    repository = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'GunplaRepository')
    functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    methods = {n.name: n for n in repository.body if isinstance(n, ast.FunctionDef)}
    summary, filters = methods['summary_rows'], methods['filters']
    append = [n for n in ast.walk(summary) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
              and n.func.attr == 'append' and isinstance(n.func.value, ast.Name) and n.func.value.id == 'rows'
              and n.args and isinstance(n.args[0], ast.Dict)]
    snapshots = [n for n in ast.walk(summary) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and n.func.attr == 'snapshot' and len(n.args) >= 2 and isinstance(n.args[0], ast.Constant) and n.args[0].value == 'gunpla']
    loops = [n for n in ast.walk(summary) if isinstance(n, ast.For) and isinstance(n.target, ast.Name) and n.target.id == 'row'
             and any(isinstance(s, ast.Assign) and isinstance(s.value, ast.Attribute) and isinstance(s.value.value, ast.Name)
                     and s.value.value.id == 'row' and s.value.attr == 'data' for s in n.body)]
    if not (len(append) == len(snapshots) == len(loops) == 1):
        raise RuntimeError('Unrecognized Mac summary_rows; source left unchanged')
    dictionary = append[0].args[0]
    indices = [i for i, key in enumerate(dictionary.keys) if isinstance(key, ast.Constant) and key.value == 'series_ids']
    value = ast.parse("product_series(row.source_key, row.name, row.data.get('series_ids'))", mode='eval').body
    if indices:
        dictionary.values[indices[-1]] = value
    else:
        dictionary.keys.append(ast.Constant(value='series_ids')); dictionary.values.append(value)
    loops[0].body.insert(0, ast.parse('if excluded_product(row.source_key, row.name):\n    continue').body[0])
    snapshots[0].args[1] = ast.parse("str(revision) + ':' + classification()[1]", mode='eval').body
    groups = [n for n in ast.walk(filters) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'series_groups']
    years = [n for n in ast.walk(functions['series_groups']) if isinstance(n, ast.Assign)
             and any(isinstance(t, ast.Name) and t.id == 'year' for t in n.targets)]
    caches = [n for n in ast.walk(functions['cached']) if isinstance(n, ast.Call)
              and isinstance(n.func, ast.Name) and n.func.id == 'public_cached' and len(n.args) > 3]
    if not (len(groups) == len(years) == len(caches) == 1):
        raise RuntimeError('Unrecognized Mac classification functions; source left unchanged')
    groups[0].args[0] = ast.Call(func=ast.Name(id='work_rows', ctx=ast.Load()), args=[groups[0].args[0],
        ast.parse("{key for row in self.summary_rows() for key in row['series_ids']}", mode='eval').body], keywords=[])
    years[0].value = ast.parse("series_years().get(row.source_key, classification()[0]['series'].get(row.source_key, {})).get('year')", mode='eval').body
    caches[0].args[3] = ast.parse("view + ':' + classification()[1]", mode='eval').body
    lines = source.splitlines(keepends=True)
    for node in sorted([summary, filters, functions['series_groups'], functions['cached']], key=lambda n: n.lineno, reverse=True):
        ast.fix_missing_locations(node)
        indent = ' ' * node.col_offset
        replacement = '\n'.join(indent + line if line else '' for line in ast.unparse(node).splitlines()) + '\n'
        lines[node.lineno - 1:node.end_lineno] = [replacement]
    result = ''.join(lines)
    imported = 'from .gunpla_classification import classification, product_series, work_rows, excluded_product\n'
    insertion = next(n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom)) and not (isinstance(n, ast.ImportFrom) and n.module == '__future__')).lineno - 1
    # Lines preceding the first import were not changed by the function edits.
    result_lines = result.splitlines(keepends=True)
    result_lines.insert(insertion, imported)
    result = ''.join(result_lines)
    ast.parse(result)
    return result.encode('utf-8')


def merge_file(name, base, local, remote):
    if local == remote or remote == base:
        return local
    if local == base:
        return remote
    if base is None or local is None or remote is None or b'\x00' in base + local + remote:
        raise RuntimeError('Conflicting file creation/deletion/binary: ' + name)
    with tempfile.TemporaryDirectory() as directory:
        paths = [Path(directory) / label for label in ['local', 'base', 'remote']]
        for path, content in zip(paths, [local, base, remote]):
            path.write_bytes(content.replace(b'\r\n', b'\n'))
        merged = subprocess.run(['git', 'merge-file', '-p', *map(str, paths)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if merged.returncode == 0:
        return merged.stdout
    if merged.returncode < 0 or merged.returncode >= 128:
        raise RuntimeError('Git merge failed: ' + name)
    pair = tuple(hashlib.sha256(content.replace(b'\r\n', b'\n')).hexdigest() for content in [base, remote])
    if KNOWN_CONFLICTS.get(name) == pair:
        if name == 'backend/app/gunpla.py':
            result = repair_gunpla(local)
        else:
            rules = '\n/* Year index alignment; keep Mac theme customizations. */\n#year-tabs{display:grid;grid-template-columns:repeat(auto-fill,minmax(74px,1fr));gap:8px}#year-tabs>.region-tab{width:100%;min-width:0;padding:9px 6px;text-align:center}\n'
            result = local + rules.encode()
        log('MERGED_MAC_CUSTOMIZATION ' + name)
        return result
    raise RuntimeError('Unresolved source conflict: ' + name)


def git_blob(git, revision, name):
    exists = subprocess.run(git + ['cat-file', '-e', revision + ':' + name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return run(git + ['show', revision + ':' + name], capture=True) if exists.returncode == 0 else None


def verify_files(root, names):
    expected = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() if (root / name).is_file() else None for name in names}
    code = """import hashlib,json,sys
from pathlib import Path
for name,digest in json.loads(sys.argv[1]).items():
 p=Path('/app')/name
 assert (p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest()==digest) if digest else not p.exists(), 'Container file mismatch: '+name
print('VERIFIED_BACKEND_FILES',len(json.loads(sys.argv[1])))
"""
    run(['docker', 'exec', 'little-atlas-mac-api-1', 'python', '-c', code, json.dumps(expected)])
    if (root / 'backend/app/gunpla_classification.py').is_file():
        code = """from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from backend.app.config import Settings
from backend.app.gunpla import GunplaRepository
engine=create_engine(Settings().database_url)
with Session(engine) as session:
 rows={r['id']:r for r in GunplaRepository(session).summary_rows()}
 for key,work in [('1189','146'),('875','146'),('2372','89')]:
  if key in rows:
   assert work in rows[key]['series_ids'], 'Live classification mismatch: '+key
 print('CLASSIFICATION_OK X='+str(sum('146' in r['series_ids'] for r in rows.values()))+' checked_DX='+str([k for k in ['1189','875'] if k in rows]))
engine.dispose()
"""
        run(['docker', 'exec', 'little-atlas-mac-api-1', 'python', '-c', code])


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
    planned = {}
    for name in names:
        local_path = root / name
        if local_path.is_symlink() or (local_path.exists() and not local_path.is_file()):
            raise RuntimeError('Only regular source files can be updated: ' + name)
        local = local_path.read_bytes() if local_path.exists() else None
        planned[name] = merge_file(name, git_blob(git, previous, name), local, git_blob(git, target, name))
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
        for name, content in planned.items():
            source = root / name
            if content is None:
                if source.exists():
                    source.unlink()
            else:
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes(content)
        compose(root, 'build', 'api')
        switched = True
        compose(root, 'up', '-d', '--no-deps', '--no-build', 'api')
        healthy()
        verify_files(root, names)
        save_revision(revision_file, target)
        log('UPDATE_OK ' + target[:12] + ' readiness=200 verified_files=' + str(len(names)) + ' backup=' + str(backup))
    except BaseException:
        for name, existed in manifest.items():
            source = root / name
            if existed:
                source.parent.mkdir(parents=True, exist_ok=True)
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
