"""Interactive deployment transport; SSH passwords are never persisted."""
import getpass
import hashlib
import json
from pathlib import Path
import sys
import paramiko

HOST = '117.72.11.77'
HOST_KEY = '6734b72ff7dae246e9a908019b6e4b37ef0dbc39dcedb9a57bd148edffb7cc4c'


class PinnedHostKey(paramiko.MissingHostKeyPolicy):
    def missing_host_key(self, client, hostname, key):
        if hashlib.sha256(key.asbytes()).hexdigest() != HOST_KEY:
            raise RuntimeError('Server host key changed')


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(PinnedHostKey())
    client.connect(HOST, username='root', password=getpass.getpass('SSH password: '), look_for_keys=False, allow_agent=False, timeout=20)
    print('CONNECTED; send JSON commands', flush=True)
    try:
        for line in sys.stdin:
            try:
                entry = json.loads(line)
                if entry.get('quit'):
                    break
                if 'upload' in entry:
                    with client.open_sftp() as sftp:
                        sftp.put(entry['upload'], entry['target'])
                    print('UPLOAD_OK', flush=True)
                    continue
                if 'download' in entry:
                    Path(entry['target']).parent.mkdir(parents=True, exist_ok=True)
                    with client.open_sftp() as sftp:
                        sftp.get(entry['download'], entry['target'])
                    print('DOWNLOAD_OK', flush=True)
                    continue
                stdin, stdout, stderr = client.exec_command('python3 -' if 'python' in entry else entry['command'], timeout=entry.get('timeout', 60))
                if 'python' in entry:
                    stdin.write(entry['python'])
                stdin.channel.shutdown_write()
                channel = stdout.channel
                import time
                while not channel.exit_status_ready() or channel.recv_ready() or channel.recv_stderr_ready():
                    if channel.recv_ready():
                        print(channel.recv(32768).decode(errors='replace'), end='', flush=True)
                    if channel.recv_stderr_ready():
                        print(channel.recv_stderr(32768).decode(errors='replace'), end='', flush=True)
                    time.sleep(.1)
                print('\nREMOTE_EXIT=' + str(channel.recv_exit_status()), flush=True)
            except Exception as error:
                print('TRANSPORT_ERROR=' + type(error).__name__ + ': ' + str(error), flush=True)
    finally:
        client.close()


if __name__ == '__main__':
    main()
