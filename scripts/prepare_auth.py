"""Project-only TLS, fail-closed rollout and private account preparation."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app.audit import audit, configure_audit

ROOT = Path('/opt/dual-catalog')
PROXY = 'dual-catalog-preview-proxy'
IP = '117.72.11.77'
IMAGE = 'dual-catalog:0.10.0'


def run(command, **kwargs):
    return subprocess.run(command, check=True, text=True, **kwargs)


def private_write(path, data, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data)
    path.chmod(mode)


def values(path):
    return dict(line.split('=', 1) for line in path.read_text().splitlines() if '=' in line and not line.lstrip().startswith('#'))


def artifacts(env):
    target = (Path(values(ROOT / env).get('PROJECT_DATA_DIR', str(ROOT / 'data'))) / 'artifacts').resolve()
    if ROOT.resolve() not in target.parents:
        raise RuntimeError('project artifacts must remain inside the project root')
    return target


def account_command(env, arguments, image=IMAGE):
    return ['docker', 'run', '--rm', '--network', 'none', '--memory', '256m', '--user', '10001:10001', '--env-file', str(ROOT / env),
            '-v', str(artifacts(env)) + ':/app/artifacts', '--entrypoint', 'python', image, '-m', 'backend.app.auth_cli', *arguments]


def snapshot():
    folder = ROOT / 'backups' / ('auth-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f'))
    folder.mkdir(parents=True, mode=0o700)
    for name in ['.env', '.env.demo', 'preview-nginx.conf']:
        target = folder / name
        shutil.copyfile(ROOT / name, target)
        target.chmod(0o600)
    return folder


def gate_file():
    directory = ROOT / 'tls/gates'
    directory.mkdir(parents=True, exist_ok=True, mode=0o755)
    directory.chmod(0o755)
    return directory / 'maintenance'


def json_get(url):
    with urllib.request.urlopen(url, timeout=15) as response:
        return json.load(response)


def verify_private_backend():
    for port in [8092, 8093]:
        ready = json_get(f'http://127.0.0.1:{port}/health/ready')
        if ready.get('status') != 'ready' or ready.get('revision') != '0004_tomica_news':
            raise RuntimeError('catalog readiness mismatch')
        try:
            json_get(f'http://127.0.0.1:{port}/api/tomica?limit=1')
        except urllib.error.HTTPError as error:
            if error.code != 401 or json.load(error).get('code') != 'AUTH_REQUIRED':
                raise RuntimeError('private authentication is not enforced') from None
        else:
            raise RuntimeError('refusing to open anonymous catalog')
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/preview/', timeout=15) as response:
            if not response.geturl().split('?', 1)[0].endswith('/login/'):
                raise RuntimeError('private page does not lead to login')
    owner = json.loads((ROOT / 'auth-owner.json').read_text())['username']
    info = json.loads(run(account_command('.env', ['list-users'], image=values(ROOT / '.env')['APP_IMAGE']), capture_output=True).stdout)
    if not any(u['username'] == owner and not u['disabled'] for u in info['users']):
        raise RuntimeError('owner account is missing or disabled')
    if json_get('https://' + IP + '/health/ready').get('status') != 'ready':
        raise RuntimeError('trusted HTTPS is not ready')


def set_gate(mode):
    if mode not in {'closed', 'open'}:
        raise ValueError('invalid maintenance mode')
    flag = gate_file()
    if mode == 'closed':
        private_write(flag, 'private deployment in progress\n', 0o644)
    else:
        verify_private_backend()
        flag.unlink(missing_ok=True)
    audit('auth_gate_updated', channel='deploy', mode=mode)


def mounts(config):
    return ['-v', str(config) + ':/etc/nginx/nginx.conf:ro', '-v', str(ROOT / 'data/artifacts/logs') + ':/var/log/dual-catalog',
            '-v', str(ROOT / 'tls/webroot') + ':/var/www/dual-catalog-acme:ro',
            '-v', str(ROOT / 'tls/config/live') + ':/etc/letsencrypt/live:ro',
            '-v', str(ROOT / 'tls/config/archive') + ':/etc/letsencrypt/archive:ro',
            '-v', str(ROOT / 'tls/gates') + ':/var/run/dual-catalog-gates:ro']


def check_config(content, image):
    stage = ROOT / 'preview-nginx.auth-next.conf'
    private_write(stage, content)
    try:
        run(['docker', 'run', '--rm', '--network', 'none', '--memory', '64m', *mounts(stage), image, 'nginx', '-t'])
    finally:
        stage.unlink(missing_ok=True)


def challenge_config():
    prefix = (ROOT / 'app/deploy/preview-nginx.conf').read_text().split('    server {', 1)[0]
    return prefix + '''    server {
        listen 80;
        location ^~ /.well-known/acme-challenge/ { root /var/www/dual-catalog-acme; try_files $uri =404; }
        location = /health/ready { proxy_pass http://127.0.0.1:8092; }
        location / { return 503; }
    }
}
'''


def install_challenge_proxy(image):
    content = challenge_config()
    check_config(content, image)
    previous = PROXY + '-before-auth-' + datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
    # The file bind mount must keep its inode.
    (ROOT / 'preview-nginx.conf').write_text(content)
    run(['docker', 'stop', PROXY])
    run(['docker', 'rename', PROXY, previous])
    try:
        run(['docker', 'run', '-d', '--name', PROXY, '--network', 'host', '--restart', 'unless-stopped', '--memory', '128m',
             '--log-opt', 'max-size=10m', '--log-opt', 'max-file=3', *mounts(ROOT / 'preview-nginx.conf'), image])
        run(['docker', 'exec', PROXY, 'nginx', '-t'])
    except BaseException:
        subprocess.run(['docker', 'rm', '-f', PROXY], check=False, capture_output=True)
        # On rollback the old proxy reads the same hard-closed HTTP config.
        run(['docker', 'rename', previous, PROXY])
        run(['docker', 'start', PROXY])
        raise
    private_write(ROOT / 'tls/proxy-backup.json', json.dumps({'container': previous, 'image': image}))


def prepare_tls():
    snapshot()
    for name in ['webroot', 'config', 'config/live', 'config/archive', 'work', 'logs']:
        (ROOT / 'tls' / name).mkdir(parents=True, exist_ok=True, mode=0o700)
    (ROOT / 'tls/webroot').chmod(0o755)
    set_gate('closed')
    image = run(['docker', 'inspect', '--format', '{{.Image}}', PROXY], capture_output=True).stdout.strip()
    install_challenge_proxy(image)
    common = [str(ROOT / 'certbot-venv/bin/certbot'), 'certonly', '--webroot', '--webroot-path', str(ROOT / 'tls/webroot'),
              '--ip-address', IP, '--preferred-profile', 'shortlived', '--cert-name', IP,
              '--config-dir', str(ROOT / 'tls/config'), '--work-dir', str(ROOT / 'tls/work'), '--logs-dir', str(ROOT / 'tls/logs'),
              '--non-interactive', '--agree-tos', '--register-unsafely-without-email']
    run([*common, '--dry-run'])
    run(common)
    content = (ROOT / 'app/deploy/preview-nginx.conf').read_text()
    check_config(content, image)
    (ROOT / 'preview-nginx.conf').write_text(content)
    run(['docker', 'exec', PROXY, 'nginx', '-t'])
    run(['docker', 'exec', PROXY, 'nginx', '-s', 'reload'])
    units = Path('/etc/systemd/system')
    private_write(units / 'dual-catalog-cert-renew.service', '[Unit]\nDescription=Renew dual catalog IP TLS certificate\n[Service]\nType=oneshot\nExecStart=/usr/bin/python3 /opt/dual-catalog/app/scripts/renew_tls.py\n', 0o644)
    private_write(units / 'dual-catalog-cert-renew.timer', '[Unit]\nDescription=Check dual catalog IP certificate every twelve hours\n[Timer]\nOnCalendar=*-*-* 00,12:00:00\nRandomizedDelaySec=300\nPersistent=true\n[Install]\nWantedBy=timers.target\n', 0o644)
    run(['systemctl', 'daemon-reload'])
    run(['systemctl', 'enable', '--now', 'dual-catalog-cert-renew.timer'])
    audit('private_tls_ready', channel='deploy', address=IP, certificate_profile='shortlived')


def prepare_accounts(username):
    username = username.strip().casefold()
    snapshot()
    for env in ['.env', '.env.demo']:
        path = ROOT / env
        existing = values(path)
        changes = {'AUTH_ENABLED': 'true', 'AUTH_COOKIE_SECURE': 'true', 'AUTH_STORE_PATH': '/app/artifacts/auth/accounts.sqlite3',
                   'AUTH_SERVICE_TOKEN': existing.get('AUTH_SERVICE_TOKEN') or secrets.token_urlsafe(32)}
        lines = [line for line in path.read_text().splitlines() if line.split('=', 1)[0] not in changes]
        private_write(path, '\n'.join(lines + [key + '=' + value for key, value in changes.items()]) + '\n')
        directory = artifacts(env) / 'auth'
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700); os.chown(directory, 10001, 10001)
        log = artifacts(env) / 'logs/auth.jsonl'
        log.parent.mkdir(parents=True, exist_ok=True)
        log.touch(mode=0o600, exist_ok=True); log.chmod(0o600); os.chown(log, 10001, 10001)
    from scripts.prepare_logging import rotation
    rotation()
    info = json.loads(run(account_command('.env', ['list-users']), capture_output=True).stdout)
    if not info['users']:
        run(account_command('.env', ['create-user', username, '--generate', '--output-file', '/app/artifacts/auth/login-bootstrap.json']))
    elif not any(u['username'] == username and not u['disabled'] for u in info['users']):
        raise RuntimeError('existing account does not match the requested owner')
    private_write(ROOT / 'auth-owner.json', json.dumps({'username': username}))
    audit('private_accounts_prepared', channel='deploy', username=username)


def finalize_account():
    username = json.loads((ROOT / 'auth-owner.json').read_text())['username']
    run(account_command('.env', ['reset-password', username, '--generate', '--output-file', '/app/artifacts/auth/login-bootstrap.json'], image=values(ROOT / '.env')['APP_IMAGE']))
    audit('private_owner_credentials_rotated', channel='deploy', username=username)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest='command', required=True)
    actions.add_parser('tls')
    actions.add_parser('accounts').add_argument('--username', required=True)
    actions.add_parser('gate').add_argument('--mode', choices=['closed', 'open'], required=True)
    actions.add_parser('finalize')
    args = parser.parse_args(argv)
    configure_audit(ROOT / 'data/artifacts/logs', channels={'deploy'})
    if args.command == 'tls': prepare_tls()
    elif args.command == 'accounts': prepare_accounts(args.username)
    elif args.command == 'gate': set_gate(args.mode)
    else: finalize_account()
    print(json.dumps({'status': 'pass', 'operation': args.command}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
