import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--containers', action='store_true')
    parser.add_argument('--wechat', action='store_true')
    args = parser.parse_args()
    report = {'python': sys.version.split()[0]}
    for tool in ['node', 'npm'] + (['docker'] if args.containers else []):
        binary = shutil.which(tool)
        command = [binary, 'info' if tool == 'docker' else '--version'] if binary else []
        result = subprocess.run(command, capture_output=True, text=True) if command else None
        report[tool] = {'exit_code': result.returncode if result else 2, 'output': (result.stdout + result.stderr).strip() if result else 'not found'}
    if args.wechat:
        report['wechat'] = {'exit_code': 0 if Path(os.environ.get('WECHAT_CLI_PATH', '__missing__')).is_file() else 2}
    print(json.dumps(report, ensure_ascii=True))
    return int(any(isinstance(v, dict) and v['exit_code'] for v in report.values()))


if __name__ == '__main__':
    raise SystemExit(main())
