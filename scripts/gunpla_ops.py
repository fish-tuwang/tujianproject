"""Project-scoped migration backups and scheduled Gunpla synchronization."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from urllib.parse import unquote, urlsplit

from scripts.prepare_auth import values


def artifact_path(root, env):
    path = (Path(values(root / env).get('PROJECT_DATA_DIR', str(root / 'data'))) / 'artifacts').resolve()
    if root.resolve() not in path.parents:
        raise ValueError('project artifact path escaped')
    return path


def container(root, env, image, arguments, *, mounts=(), network='host'):
    return ['docker', 'run', '--rm', '--network', network, '--memory', '384m', '--pids-limit', '128', '--user', '10001:10001', '--env-file', str(root / env), '-v', str(artifact_path(root, env)) + ':/app/artifacts', *mounts, '--entrypoint', 'python', image, *arguments]


def backup_and_freeze(root, image, source):
    source = Path(source).resolve()
    allowed = (artifact_path(root, '.env') / 'gunpla-source').resolve()
    if allowed not in source.parents or source.suffix != '.json' or source.stat().st_size > 128 * 1024 * 1024:
        raise ValueError('use a project Gunpla export')
    raw = source.read_bytes()
    document = json.loads(raw)
    if document.get('schema_version') != 1 or not isinstance(document.get('entries'), list) or not any(r.get('kind') == 'product' for r in document['entries']):
        raise ValueError('Gunpla export contains no usable models')
    folder = root / 'backups' / ('gunpla-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f'))
    folder.mkdir(parents=True, mode=0o700)
    target = folder / 'catalog-frozen.json'
    target.write_bytes(raw); target.chmod(0o600); os.chown(target, 10001, 10001)
    for name in ['.env', '.env.demo', 'auth-owner.json']:
        shutil.copyfile(root / name, folder / name); (folder / name).chmod(0o600)
    for env in ['.env', '.env.demo']:
        settings = values(root / env)
        parsed = urlsplit(settings['DATABASE_URL'])
        backup = folder / ('production.dump' if env == '.env' else 'demo.dump')
        backup.touch(mode=0o600)
        child_env = {**os.environ, 'PGPASSWORD': unquote(parsed.password or '')}
        command = ['/www/server/pgsql/bin/pg_dump', '-h', parsed.hostname or '127.0.0.1', '-p', str(parsed.port or 5432), '-U', unquote(parsed.username or ''), '-d', unquote(parsed.path.lstrip('/')), '-Fc', '--no-owner', '-f', str(backup)]
        subprocess.run(command, env=child_env, check=True, capture_output=True)
        subprocess.run(['/www/server/pgsql/bin/pg_restore', '--list', str(backup)], check=True, capture_output=True)
        backup.chmod(0o600)
        if backup.stat().st_size == 0:
            raise RuntimeError('empty project database backup')
        auth = folder / ('auth-production' if env == '.env' else 'auth-demo')
        auth.mkdir(mode=0o700)
        os.chown(auth, 10001, 10001)
        code = "import sqlite3,os; source=sqlite3.connect('file:/app/artifacts/auth/accounts.sqlite3?mode=ro',uri=True); target=sqlite3.connect('/app/auth-backup/accounts.sqlite3'); source.backup(target); target.close(); source.close(); os.chmod('/app/auth-backup/accounts.sqlite3',0o600)"
        subprocess.run(container(root, env, image, ['-c', code], mounts=['-v', str(auth) + ':/app/auth-backup'], network='none'), check=True, capture_output=True)
    receipt = {'frozen_sha256': hashlib.sha256(raw).hexdigest(), 'source_status': document.get('coverage', {}).get('status'), 'products': sum(r.get('kind') == 'product' for r in document['entries'])}
    (folder / 'snapshot.json').write_text(json.dumps(receipt)); (folder / 'snapshot.json').chmod(0o600)
    return target


def account_fingerprints(root, image):
    result = {}
    code = "import sqlite3,hashlib,json; db=sqlite3.connect('file:/app/artifacts/auth/accounts.sqlite3?mode=ro',uri=True); rows=db.execute('SELECT username,password_hash,disabled,must_change_password,created_at FROM accounts ORDER BY username').fetchall(); print(json.dumps({'count':len(rows),'sha256':hashlib.sha256(json.dumps(rows).encode()).hexdigest()})); db.close()"
    for env in ['.env', '.env.demo']:
        output = subprocess.run(container(root, env, image, ['-c', code], network='none'), check=True, capture_output=True, text=True)
        result[env] = json.loads(output.stdout)
    return result


def install_timer(root, units=Path('/etc/systemd/system')):
    service = '[Unit]\nDescription=Synchronize private Gunpla models\nAfter=network-online.target docker.service\n[Service]\nType=oneshot\nEnvironmentFile=' + str(root / '.env') + '\nExecStart=/usr/bin/docker run --rm --name dual-catalog-gunpla-sync --network host --memory 384m --pids-limit 128 --user 10001:10001 --env-file ' + str(root / '.env') + ' -v ' + str(artifact_path(root, '.env')) + ':/app/artifacts --entrypoint python ${APP_IMAGE} -m scripts.sync_gunpla --mode incremental --directory /app/artifacts/gunpla-source\nTimeoutStartSec=10800\nTimeoutStopSec=60\nExecStopPost=-/usr/bin/docker stop dual-catalog-gunpla-sync\n'
    timer = '[Unit]\nDescription=Check official Gunpla models daily\n[Timer]\nOnCalendar=*-*-* 03:30:00 Asia/Shanghai\nPersistent=true\n[Install]\nWantedBy=timers.target\n'
    for name, text in [('dual-catalog-gunpla-sync.service', service), ('dual-catalog-gunpla-sync.timer', timer)]:
        path = units / name; path.write_text(text); path.chmod(0o644)
    subprocess.run(['systemd-analyze', 'verify', str(units / 'dual-catalog-gunpla-sync.service'), str(units / 'dual-catalog-gunpla-sync.timer')], check=True, capture_output=True)
    subprocess.run(['systemd-analyze', 'calendar', '*-*-* 03:30:00 Asia/Shanghai'], check=True, capture_output=True)
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', 'enable', '--now', 'dual-catalog-gunpla-sync.timer'], check=True)
