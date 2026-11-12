"""Prepare and inspect only the catalog's own QQ bridge and account container."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request

ROOT = Path('/opt/dual-catalog')
ENV = ROOT / '.env.qq-bot'
COMPOSE = ['docker', 'compose', '--env-file', str(ENV), '-f', str(ROOT / 'app/compose.qq.yaml')]
IMAGE = 'mlikiowa/napcat-docker@sha256:696e9574a0f6fb2f86cbecba8a32048f2a5823117dc9b13c6c02637ad890fa8b'


def run(args, **kwargs):
    return subprocess.run(args, check=True, text=True, **kwargs)


def environment(path):
    return {line.split('=', 1)[0]: line.split('=', 1)[1].strip().strip('"\'') for line in path.read_text().splitlines() if '=' in line and not line.lstrip().startswith('#')}


def write(path, value, uid=0):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.next')
    temporary.write_text(value)
    temporary.chmod(0o600)
    os.chown(temporary, uid, uid)
    os.replace(temporary, path)


def snapshot():
    ids = run(['docker', 'ps', '-aq'], capture_output=True).stdout.split()
    rows = json.loads(run(['docker', 'inspect', *ids], capture_output=True).stdout)
    containers = {row['Name']: row['Id'] for row in rows if row['Name'].startswith('/dual-catalog') and not row['Name'].startswith('/dual-catalog-qq-')}
    accounts, health = {}, {}
    for env in ['data', 'demo']:
        with sqlite3.connect('file:' + str(ROOT / env / 'artifacts/auth/accounts.sqlite3') + '?mode=ro', uri=True) as db:
            assert db.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
            account_rows = db.execute('SELECT username,password_hash,disabled,must_change_password,created_at FROM accounts ORDER BY username').fetchall()
        accounts[env] = hashlib.sha256(json.dumps(account_rows).encode()).hexdigest()
    for port in [8092, 8093]:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/health/ready', timeout=5) as response:
            health[str(port)] = json.load(response)
        assert health[str(port)] == {'status': 'ready', 'revision': '0005_gunpla'}
    return {'containers': containers, 'accounts': accounts, 'health': health}


def prepare(account, groups):
    if not re.fullmatch(r'[1-9][0-9]{4,11}', account):
        raise ValueError('provide the original QQ number')
    if groups != '*' and (not groups or any(not re.fullmatch(r'[1-9][0-9]*', value.strip()) for value in groups.split(','))):
        raise ValueError('provide explicit group IDs or *')
    if ENV.exists():
        raise RuntimeError('already prepared; use configure instead of replacing login state')
    before = snapshot()
    parent = ROOT / 'qq'
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    for name, uid in [('state', 10001), ('account', 10002), ('config', 10002)]:
        path = parent / name
        path.mkdir(mode=0o700, exist_ok=True)
        os.chown(path, uid, uid)
    original = environment(ROOT / '.env')
    token = original.get('AUTH_SERVICE_TOKEN', '')
    assert len(token) >= 32
    onebot_token, webui_token = secrets.token_urlsafe(36), secrets.token_urlsafe(36)
    values = {'QQ_ACCOUNT': account, 'QQ_ALLOWED_GROUPS': groups, 'QQ_ONEBOT_TOKEN': onebot_token,
              'QQ_CATALOG_TOKEN': token, 'QQ_NAPCAT_IMAGE': IMAGE,
              'QQ_CATALOG_API': 'http://127.0.0.1:8092', 'QQ_ACCOUNT_API': 'http://127.0.0.1:3002',
              'QQ_PUBLIC_BASE': 'https://117.72.11.77'}
    write(ENV, ''.join(key + '=' + value + '\n' for key, value in values.items()))
    config = parent / 'config'
    network = {'httpServers': [{'name': 'catalog-local-api', 'enable': True, 'host': '127.0.0.1', 'port': 3002, 'enableCors': False, 'enableWebsocket': False, 'messagePostFormat': 'array', 'token': onebot_token, 'debug': False}],
               'httpClients': [{'name': 'catalog-queries', 'enable': True, 'url': 'http://127.0.0.1:8096/onebot/events', 'messagePostFormat': 'array', 'reportSelfMessage': False, 'token': onebot_token, 'debug': False}],
               'websocketServers': [], 'websocketClients': []}
    onebot = json.dumps({'network': network, 'musicSignUrl': '', 'enableLocalFile2Url': False, 'parseMultMsg': False}, indent=2)
    for name in ['onebot11.json', 'onebot11_' + account + '.json']:
        write(config / name, onebot, 10002)
    write(config / 'webui.json', json.dumps({'host': '127.0.0.1', 'port': 6099, 'token': webui_token, 'loginRate': 3}), 10002)
    write(config / 'napcat.json', json.dumps({'fileLog': False, 'consoleLog': True, 'consoleLogLevel': 'info'}), 10002)
    record = {'prepared_at': datetime.now(timezone.utc).isoformat(), 'qq_account': account,
              'groups': groups, 'image': IMAGE, 'before': before, 'status': 'prepared'}
    write(parent / 'deployment.json', json.dumps(record, indent=2))
    print('QQ_PREPARED; ACCOUNT=' + account + '; GROUP_SCOPE=' + groups + '; TOKENS_NOT_PRINTED', flush=True)


def start():
    record_path = ROOT / 'qq/deployment.json'
    record = json.loads(record_path.read_text())
    assert snapshot() == record['before'], 'existing catalog changed before QQ start'
    run(COMPOSE + ['build', 'bridge'], cwd=ROOT / 'app')
    run(COMPOSE + ['up', '-d'], cwd=ROOT / 'app')
    assert snapshot() == record['before'], 'existing catalog changed during QQ start'
    record.update(status='waiting_for_qq_login', started_at=datetime.now(timezone.utc).isoformat(), catalog_containers_unchanged=True, accounts_unchanged=True)
    write(record_path, json.dumps(record, indent=2))
    sys.path.insert(0, str(ROOT / 'app'))
    from backend.app.audit import audit, configure_audit
    configure_audit(ROOT / 'data/artifacts/logs', channels={'deploy'})
    audit('qq_catalog_deployed', channel='deploy', qq_account=record['qq_account'], groups=record['groups'], image=IMAGE, catalog_containers_unchanged=True, accounts_unchanged=True)
    print('QQ_COMPONENTS_STARTED; CATALOG_UNCHANGED; LOGIN_NOT_YET_VERIFIED', flush=True)


def status():
    values = environment(ENV)
    result = {'qq_account': values['QQ_ACCOUNT'], 'groups': values['QQ_ALLOWED_GROUPS']}
    for name in ['live', 'ready']:
        try:
            with urllib.request.urlopen('http://127.0.0.1:8096/health/' + name, timeout=5) as response:
                result[name] = json.load(response)
        except urllib.error.HTTPError as error:
            result[name] = json.load(error)
        except OSError as error:
            result[name] = {'status': 'unavailable', 'error': type(error).__name__}
    print(json.dumps(result), flush=True)


def configure(account, groups):
    values = environment(ENV)
    if account and account != values['QQ_ACCOUNT']:
        raise RuntimeError('changing QQ identity requires a separate login setup')
    if groups != '*' and any(not re.fullmatch(r'[1-9][0-9]*', v.strip()) for v in groups.split(',')):
        raise ValueError('invalid group scope')
    values['QQ_ALLOWED_GROUPS'] = groups
    write(ENV, ''.join(key + '=' + value + '\n' for key, value in values.items()))
    run(COMPOSE + ['up', '-d', '--no-deps', 'bridge'])
    print('QQ_GROUP_SCOPE_UPDATED', flush=True)


def login_qr():
    config = json.loads((ROOT / 'qq/config/webui.json').read_text())
    credential = None

    def post(path, body):
        headers = {'Content-Type': 'application/json'}
        if credential:
            headers['Authorization'] = 'Bearer ' + credential
        request = urllib.request.Request('http://127.0.0.1:6099/api' + path, json.dumps(body).encode(), headers, method='POST')
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.load(response)
        if result.get('code') != 0:
            raise RuntimeError('QQ login API rejected the request: ' + str(result.get('message')))
        return result.get('data') or {}

    signed = hashlib.sha256((config['token'] + '.napcat').encode()).hexdigest()
    credential = post('/auth/login', {'hash': signed})['Credential']
    current = post('/QQLogin/CheckLoginStatus', {})
    if current.get('isLogin'):
        print('QQ_ALREADY_LOGGED_IN', flush=True)
        return
    updated = post('/QQLogin/RefreshQRcode', {})
    assert updated.get('qrcodeurl') and updated['qrcodeurl'] != current.get('qrcodeurl')
    target = ROOT / 'qq/login-qr.png'
    run(['docker', 'cp', 'dual-catalog-qq-account:/app/napcat/cache/qrcode.png', str(target)], capture_output=True)
    target.chmod(0o600)
    print('QQ_LOGIN_QR_REFRESHED: ' + str(target), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['prepare', 'start', 'status', 'configure', 'login-qr'])
    parser.add_argument('--account', default='')
    parser.add_argument('--groups', default='')
    args = parser.parse_args()
    if args.operation == 'prepare':
        prepare(args.account, args.groups)
    elif args.operation == 'start':
        start()
    elif args.operation == 'configure':
        configure(args.account, args.groups)
    elif args.operation == 'login-qr':
        login_qr()
    else:
        status()


if __name__ == '__main__':
    main()
