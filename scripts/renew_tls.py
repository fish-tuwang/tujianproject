"""Renew this project's IP certificate and reload only its own proxy."""
import argparse
from pathlib import Path
import subprocess

ROOT = Path('/opt/dual-catalog')
PROXY = 'dual-catalog-preview-proxy'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    command = [str(ROOT / 'certbot-venv/bin/certbot'), 'renew', '--non-interactive', '--cert-name', '117.72.11.77',
               '--config-dir', str(ROOT / 'tls/config'), '--work-dir', str(ROOT / 'tls/work'), '--logs-dir', str(ROOT / 'tls/logs')]
    if args.dry_run:
        command.append('--dry-run')
    subprocess.run(command, check=True)
    subprocess.run(['docker', 'exec', PROXY, 'nginx', '-t'], check=True)
    subprocess.run(['docker', 'exec', PROXY, 'nginx', '-s', 'reload'], check=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
