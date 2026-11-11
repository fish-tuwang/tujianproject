"""Validate and reload this project's proxy without restarting application services."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app.audit import audit, configure_audit
from scripts.deploy_release import plugins
from scripts.prepare_auth import ROOT, PROXY, check_config


def fetch(path, agent='Mozilla/5.0 CatalogVerification'):
    request = urllib.request.Request('https://117.72.11.77' + path, headers={'User-Agent': agent})
    try:
        response = urllib.request.urlopen(request, timeout=15)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        return response.status, response.headers, response.read(8192)


def verify():
    for _ in range(20):
        status, headers, body = fetch('/health/ready')
        if status == 200 and 'noindex' in headers.get('X-Robots-Tag', ''):
            break
        time.sleep(.25)
    else:
        raise RuntimeError('proxy readiness or new headers failed')
    assert json.loads(body) == {'status': 'ready', 'revision': '0005_gunpla'}
    assert fetch('/robots.txt')[2] == b'User-agent: *\nDisallow: /\n'
    assert fetch('/login/')[0] == 200
    assert fetch('/api/gunpla?limit=1')[0] == 401
    assert fetch('/login/', 'Googlebot/2.1')[0] == 403
    assert fetch('/api/gunpla', 'Scrapy/2.12')[0] == 403


def main():
    configure_audit(ROOT / 'data/artifacts/logs', channels={'deploy'})
    inspect = lambda: json.loads(subprocess.check_output(['docker', 'inspect', PROXY]))[0]
    before = inspect()
    target = ROOT / 'preview-nginx.conf'
    if before['HostConfig']['NetworkMode'] != 'host' or not any(m['Source'] == str(target) and m['Destination'] == '/etc/nginx/nginx.conf' for m in before['Mounts']):
        raise RuntimeError('unexpected project proxy mount')
    content = (ROOT / 'app/deploy/preview-nginx.conf').read_bytes()
    check_config(content.decode(), before['Image'])
    folder = ROOT / 'backups' / ('crawler-defense-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S'))
    folder.mkdir(mode=0o700)
    backup = folder / 'preview-nginx.conf'
    shutil.copyfile(target, backup); backup.chmod(0o600)
    unrelated = plugins()
    try:
        # Keep the inode referenced by the read-only Docker bind mount.
        target.write_bytes(content)
        subprocess.run(['docker', 'exec', PROXY, 'nginx', '-t'], check=True)
        subprocess.run(['docker', 'exec', PROXY, 'nginx', '-s', 'reload'], check=True)
        verify()
        assert inspect()['Id'] == before['Id'] and plugins() == unrelated
    except Exception:
        target.write_bytes(backup.read_bytes())
        subprocess.run(['docker', 'exec', PROXY, 'nginx', '-t'], check=True)
        subprocess.run(['docker', 'exec', PROXY, 'nginx', '-s', 'reload'], check=True)
        audit('crawler_defense_rollback', channel='deploy', backup=str(backup))
        raise
    report = {'status': 'pass', 'config_sha256': hashlib.sha256(content).hexdigest(), 'backup': str(backup), 'proxy_id_unchanged': True, 'plugins_unchanged': True, 'application_restart': False}
    audit('crawler_defense_enabled', channel='deploy', **report)
    (ROOT / 'data/artifacts/acceptance/crawler-defense-deployment.json').write_text(json.dumps(report))
    print(json.dumps(report))


if __name__ == '__main__':
    main()
