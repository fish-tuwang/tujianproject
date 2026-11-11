"""Provision a project-only Redis; run as root on the authorized server."""
import json
import os
from pathlib import Path
import pwd
import secrets
import shutil
import socket
import subprocess
import time

unit = 'dual-catalog-redis.service'
active = subprocess.run(['systemctl', 'is-active', '--quiet', unit]).returncode == 0
if not active:
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 6382))
account = 'dual-catalog-cache'
try:
    owner = pwd.getpwnam(account)
except KeyError:
    subprocess.run(['useradd', '--system', '--user-group', '--home-dir', '/var/lib/dual-catalog-redis', '--shell', '/usr/sbin/nologin', account], check=True)
    owner = pwd.getpwnam(account)
binary = Path('/usr/local/libexec/dual-catalog-redis-server')
binary.parent.mkdir(parents=True, exist_ok=True)
if not binary.exists():
    shutil.copy2('/www/server/redis/src/redis-server', binary)
    binary.chmod(0o755)
data = Path('/var/lib/dual-catalog-redis')
data.mkdir(exist_ok=True)
os.chown(data, owner.pw_uid, owner.pw_gid)
data.chmod(0o700)
config = Path('/etc/dual-catalog-redis.conf')
password = next((line.split(' ', 1)[1] for line in config.read_text().splitlines() if line.startswith('requirepass ')), '') if config.exists() else ''
password = password or secrets.token_hex(32)
config.write_text(f'''bind 127.0.0.1
port 6382
protected-mode yes
requirepass {password}
dir {data}
dbfilename dump.rdb
save 900 1
appendonly no
maxmemory 256mb
maxclients 1000
maxmemory-policy allkeys-lru
daemonize no
logfile ""
''')
os.chown(config, 0, owner.pw_gid)
config.chmod(0o640)
service = Path('/etc/systemd/system') / unit
service.write_text(f'''[Unit]
Description=Dual catalog Redis cache
After=network.target
[Service]
Type=simple
User={account}
Group={account}
ExecStart={binary} {config}
Restart=on-failure
RestartSec=2
NoNewPrivileges=true
ProtectHome=true
ProtectSystem=strict
PrivateTmp=true
ReadWritePaths={data}
MemoryMax=512M
LimitNOFILE=10000
UMask=0077
[Install]
WantedBy=multi-user.target
''')
for name, db in [('.env', 0), ('.env.demo', 1)]:
    path = Path('/opt/dual-catalog') / name
    values = dict(line.split('=', 1) for line in path.read_text().splitlines() if line and not line.startswith('#') and '=' in line)
    values['REDIS_URL'] = f'redis://:{password}@127.0.0.1:6382/{db}'
    values['CACHE_NAMESPACE'] = 'dual-catalog:v2:' + ('production' if db == 0 else 'demo')
    path.write_text(''.join(k + '=' + v + '\n' for k, v in values.items()))
    path.chmod(0o600)
subprocess.run(['systemctl', 'daemon-reload'], check=True)
subprocess.run(['systemctl', 'enable', '--now', unit], check=True)
for attempt in range(20):
    result = subprocess.run(['/usr/bin/redis-cli', '-h', '127.0.0.1', '-p', '6382', 'PING'], env={**os.environ, 'REDISCLI_AUTH': password}, capture_output=True, text=True)
    if result.returncode == 0 and result.stdout.strip() == 'PONG':
        break
    time.sleep(0.25)
if result.stdout.strip() != 'PONG':
    raise RuntimeError('cache health check failed')
print(json.dumps({'service': unit, 'port': 6382, 'bind': '127.0.0.1', 'ping': 'PONG', 'maxmemory_mb': 256, 'production_db': 0, 'demo_db': 1, 'credentials': 'retained on server only'}))
