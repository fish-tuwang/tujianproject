"""Enable private logging on this project's proxy and install scoped rotation."""
from datetime import datetime, timezone
import getpass
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app.audit import audit, configure_audit

ROOT = Path('/opt/dual-catalog')
LOGS = ROOT / 'data/artifacts/logs'
PROXY = 'dual-catalog-preview-proxy'


def run(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def proxy_logging():
    container = json.loads(run(['docker', 'inspect', PROXY], capture_output=True, text=True).stdout)[0]
    config = ROOT / 'preview-nginx.conf'
    if container['HostConfig']['NetworkMode'] != 'host' or not any(m['Source'] == str(config) and m['Destination'] == '/etc/nginx/nginx.conf' for m in container['Mounts']):
        raise RuntimeError('unexpected proxy configuration')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')
    backup = ROOT / 'backups' / ('nginx-before-logging-' + stamp + '.conf')
    backup.parent.mkdir(mode=0o700, exist_ok=True)
    shutil.copyfile(config, backup)
    backup.chmod(0o600)
    stage = ROOT / 'preview-nginx.next.conf'
    shutil.copyfile(ROOT / 'app/deploy/preview-nginx.conf', stage)
    mounts = ['-v', str(stage) + ':/etc/nginx/nginx.conf:ro', '-v', str(LOGS) + ':/var/log/dual-catalog']
    run(['docker', 'run', '--rm', '--network', 'none', '--memory', '64m', *mounts, container['Image'], 'nginx', '-t'])
    already_mounted = any(m['Source'] == str(LOGS) and m['Destination'] == '/var/log/dual-catalog' for m in container['Mounts'])
    old_config, renamed = config.read_bytes(), False
    previous = PROXY + '-before-logging-' + stamp.lower()
    try:
        config.write_bytes(stage.read_bytes())
        if already_mounted:
            run(['docker', 'exec', PROXY, 'nginx', '-t'])
            run(['docker', 'exec', PROXY, 'nginx', '-s', 'reload'])
        else:
            legacy = LOGS / ('access-legacy-' + stamp + '.log')
            with legacy.open('wb') as output:
                run(['docker', 'logs', '--timestamps', PROXY], stdout=output, stderr=subprocess.STDOUT)
            legacy.chmod(0o600)
            run(['docker', 'stop', PROXY])
            run(['docker', 'rename', PROXY, previous])
            renamed = True
            run(['docker', 'run', '-d', '--name', PROXY, '--network', 'host', '--restart', 'unless-stopped', '--log-opt', 'max-size=10m', '--log-opt', 'max-file=3', '-v', str(config) + ':/etc/nginx/nginx.conf:ro', '-v', str(LOGS) + ':/var/log/dual-catalog', container['Image']])
        # Readiness is checked after nginx has reopened its files.
        import time
        for attempt in range(20):
            try:
                with urllib.request.urlopen('http://127.0.0.1/health/ready', timeout=3) as response:
                    if response.status == 200 and response.headers.get('X-Request-ID'):
                        break
            except OSError:
                time.sleep(.25)
        else:
            raise RuntimeError('proxy logging readiness failed')
        if renamed:
            run(['docker', 'rm', previous])
        return hashlib.sha256(config.read_bytes()).hexdigest()
    except Exception:
        config.write_bytes(old_config)
        if renamed:
            subprocess.run(['docker', 'rm', '-f', PROXY], check=False)
            run(['docker', 'rename', previous, PROXY])
            run(['docker', 'start', PROXY])
        elif already_mounted:
            subprocess.run(['docker', 'exec', PROXY, 'nginx', '-s', 'reload'], check=False)
        raise
    finally:
        stage.unlink(missing_ok=True)


def rotation():
    common = '    daily\n    maxsize 20M\n    rotate 14\n    missingok\n    notifempty\n    compress\n    delaycompress\n    su root root\n'
    access = str(LOGS / 'access.jsonl') + ' {\n' + common + '    create 0640 root root\n    sharedscripts\n    postrotate\n        /usr/bin/docker exec dual-catalog-preview-proxy nginx -s reopen >/dev/null 2>&1 || true\n    endscript\n}\n'
    collection = str(LOGS / 'collection.jsonl') + ' {\n' + common + '    create 0640\n}\n'
    deploy = str(LOGS / 'deploy.jsonl') + ' {\n' + common.replace('maxsize 20M', 'maxsize 5M').replace('rotate 14', 'rotate 30') + '    create 0600 root root\n}\n'
    config = ROOT / 'logrotate.conf'
    config.write_text(access + collection + deploy)
    config.chmod(0o600)
    units = Path('/etc/systemd/system')
    (units / 'dual-catalog-logrotate.service').write_text('[Unit]\nDescription=Rotate dual catalog private logs\n[Service]\nType=oneshot\nExecStart=/usr/sbin/logrotate --state /opt/dual-catalog/logrotate.status /opt/dual-catalog/logrotate.conf\n')
    (units / 'dual-catalog-logrotate.timer').write_text('[Unit]\nDescription=Check dual catalog log size hourly\n[Timer]\nOnCalendar=hourly\nPersistent=true\nRandomizedDelaySec=60\n[Install]\nWantedBy=timers.target\n')
    run(['logrotate', '--debug', '--state', str(ROOT / 'logrotate.status'), str(config)])
    run(['systemctl', 'daemon-reload'])
    run(['systemctl', 'enable', '--now', 'dual-catalog-logrotate.timer'])


def main():
    LOGS.mkdir(mode=0o751, parents=True, exist_ok=True)
    os.chown(LOGS, 10001, 10001)
    LOGS.chmod(0o751)
    for name in ['access', 'collection', 'deploy']:
        path = LOGS / (name + '.jsonl')
        path.touch(exist_ok=True)
        path.chmod(0o600 if name == 'deploy' else 0o640)
        os.chown(path, 10001 if name == 'collection' else 0, 10001 if name == 'collection' else 0)
    configure_audit(LOGS, channels={'deploy'})
    actor = {'actor': getpass.getuser(), 'actor_ip': (os.environ.get('SSH_CONNECTION', '').split() or [None])[0]}
    audit('logging_setup_started', channel='deploy', **actor)
    try:
        digest = proxy_logging()
        rotation()
        audit('logging_setup_finished', channel='deploy', **actor, nginx_sha256=digest, log_directory=str(LOGS), rotation='hourly checks, daily/size rotation')
        print(json.dumps({'status': 'pass', 'logs': str(LOGS), 'nginx_sha256': digest}))
    except Exception as error:
        audit('logging_setup_failed', channel='deploy', **actor, error_type=type(error).__name__)
        raise


if __name__ == '__main__':
    main()
