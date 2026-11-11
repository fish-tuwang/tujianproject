"""Idempotent project-only preparation, executed on the authorized server."""
from pathlib import Path
import json
import os
import secrets
import subprocess
import tarfile
from urllib.parse import urlsplit, urlunsplit

root = Path('/opt/dual-catalog')
app = root / 'app'
app.mkdir(exist_ok=True)
with tarfile.open(root / 'deploy.tar.gz') as archive:
    for member in archive.getmembers():
        if not (app / member.name).resolve().is_relative_to(app.resolve()):
            raise RuntimeError('unsafe archive member')
    archive.extractall(app, filter='data')


def read_env(path):
    return dict(line.split('=', 1) for line in path.read_text().splitlines() if line and not line.startswith('#') and '=' in line)


def save(path, values):
    path.write_text(''.join(k + '=' + v + '\n' for k, v in values.items()))
    path.chmod(0o600)


env = read_env(root / '.env')
env.update({'APP_IMAGE': env.get('APP_IMAGE', 'dual-catalog:0.1.1'), 'APP_ENV_FILE': '/opt/dual-catalog/.env', 'PROJECT_DATA_DIR': '/opt/dual-catalog/data', 'API_PORT': '8092', 'API_BIND': '127.0.0.1', 'ADMIN_TOKEN': env.get('ADMIN_TOKEN') or secrets.token_urlsafe(40), 'ARTIFACT_DIR': '/app/artifacts/acceptance', 'ACCEPTANCE_BASE_URL': 'http://127.0.0.1:8092'})
save(root / '.env', env)
demo = dict(env)
demo.update({'DATABASE_URL': urlunsplit(urlsplit(env['DATABASE_URL'])._replace(path='/dual_catalog_demo')), 'APP_ENV_FILE': '/opt/dual-catalog/.env.demo', 'PROJECT_DATA_DIR': '/opt/dual-catalog/demo', 'API_PORT': '8093', 'API_BIND': '127.0.0.1', 'ADMIN_TOKEN': secrets.token_urlsafe(40), 'ACCEPTANCE_BASE_URL': 'http://127.0.0.1:8093'})
if not (root / '.env.demo').exists():
    save(root / '.env.demo', demo)
args = ['runuser', '-u', 'postgres', '--', '/www/server/pgsql/bin/psql', '-X', '-v', 'ON_ERROR_STOP=1', '-d', 'postgres', '-At']
result = subprocess.run(args, input="SELECT 1 FROM pg_database WHERE datname='dual_catalog_demo';", text=True, capture_output=True, check=True)
if not result.stdout.strip():
    subprocess.run(args, input='CREATE DATABASE dual_catalog_demo OWNER dual_catalog_app; REVOKE ALL ON DATABASE dual_catalog_demo FROM PUBLIC; GRANT CONNECT ON DATABASE dual_catalog_demo TO dual_catalog_app;', text=True, capture_output=True, check=True)
for name in ['data', 'demo']:
    output = root / name / 'artifacts/acceptance'
    output.mkdir(parents=True, exist_ok=True)
    for directory in [root / name, root / name / 'artifacts', output]:
        os.chown(directory, 10001, 10001)
        directory.chmod(0o750)
backup = root / 'backups'
backup.mkdir(mode=0o700, exist_ok=True)
target = backup / 'before-first-migration.dump'
if not target.exists():
    result = subprocess.run(['/www/server/pgsql/bin/pg_dump', '-h', '127.0.0.1', '-U', 'dual_catalog_app', '-d', 'dual_catalog', '-Fc', '-f', str(target)], env={**os.environ, 'PGPASSWORD': urlsplit(env['DATABASE_URL']).password}, capture_output=True)
    if result.returncode:
        raise RuntimeError('project backup failed')
    target.chmod(0o600)
print(json.dumps({'app_path': str(app), 'env_retained': True, 'demo_database': 'dual_catalog_demo', 'backup_bytes': target.stat().st_size}))
