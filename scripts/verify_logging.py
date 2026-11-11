"""Verify real private logs and rotate only this project's log files."""
import argparse
import json
from pathlib import Path
import stat
import subprocess
import sys
import time
import urllib.request
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.view_logs import records

ROOT = Path('/opt/dual-catalog')
LOGS = ROOT / 'data/artifacts/logs'


def local_request():
    with urllib.request.urlopen('http://127.0.0.1/preview/', timeout=10) as response:
        assert response.status == 200
        request_id = response.headers['X-Request-ID']
        response.read()
        return request_id


def find_access(request_id, current_only=False):
    for attempt in range(30):
        values = [json.loads(line) for line in (LOGS / 'access.jsonl').read_text().splitlines()] if current_only else records(LOGS, 'access')
        row = next((r for r in values if r['request_id'] == request_id), None)
        if row:
            return row
        time.sleep(.1)
    raise AssertionError('request ID missing from access log')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--public-request-id', required=True)
    parser.add_argument('--secret-marker', required=True)
    args = parser.parse_args()
    report = {'status': 'fail', 'checks': []}

    def check(name, value):
        assert value, name
        report['checks'].append(name)
        print('PASS ' + name, flush=True)

    public = find_access(args.public_request_id)
    check('public request has a real connection IP, ignoring both spoofed forwarding headers', public['client_ip'] not in {'198.51.100.55', '203.0.113.44', '127.0.0.1', '::1'})
    check('access JSON excludes query strings, cookies and authorization values', args.secret_marker not in json.dumps(public))
    check('quoted user-agent remains a valid JSON string', '"quoted"' in public['user_agent'])
    previous = local_request()
    find_access(previous)
    subprocess.run(['logrotate', '--force', '--state', str(ROOT / 'logrotate.status'), str(ROOT / 'logrotate.conf')], check=True)
    current = local_request()
    check('nginx continues logging to the new file after real rotation', find_access(current, current_only=True)['status'] == 200)
    check('rotated access history remains queryable', find_access(previous)['request_id'] == previous)
    timer = subprocess.run(['systemctl', 'is-active', 'dual-catalog-logrotate.timer'], capture_output=True, text=True, check=True).stdout.strip()
    check('project log rotation timer is active', timer == 'active')
    # This is a separate short-lived process, never an extra Python inside the API.
    command = ['docker', 'compose', '--env-file', str(ROOT / '.env'), '-f', str(ROOT / 'app/compose.production.yaml'), '-p', 'dual-catalog', 'run', '--rm', '--no-deps', '-T', 'api', 'python', '-m', 'backend.app.worker', 'report']
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    task_report = json.loads(result.stdout.strip().splitlines()[-1])
    check('worker reopens collection log after rotation', any(r.get('event') == 'process_started' and r.get('command') == 'report' for r in [json.loads(line) for line in (LOGS / 'collection.jsonl').read_text().splitlines()]))
    collection = list(records(LOGS, 'collection'))
    observed = [r for r in collection if r.get('event') in {'page_checked', 'page_failed'}]
    for attempt in range(45):
        if observed:
            break
        time.sleep(1)
        observed = [r for r in records(LOGS, 'collection') if r.get('event') in {'page_checked', 'page_failed'}]
    check('real scheduled source processing is recorded', bool(observed) and all(r.get('source') in {'tomica', 'pokemon'} and r.get('run_id') for r in observed))
    deployment = json.loads((ROOT / 'data/artifacts/acceptance/logging-deployment.json').read_text())
    check('successful real deployment remains logged after rotation', any(r.get('event') == 'deployment_finished' and r.get('operation_id') == deployment['operation_id'] for r in records(LOGS, 'deploy')))
    check('log files are private and not world-readable', all(not (stat.S_IMODE((LOGS / (kind + '.jsonl')).stat().st_mode) & stat.S_IROTH) for kind in ['access', 'collection', 'deploy']))
    try:
        with urllib.request.urlopen('http://127.0.0.1/data/artifacts/logs/access.jsonl', timeout=10) as response:
            public_status = response.status
    except HTTPError as error:
        public_status = error.code
    check('log files have no public download route', public_status == 404)

    report.update(status='pass', assertions=len(report['checks']), public_ip=public['client_ip'], real_page_events=len(observed), recent_runs=len(task_report['runs']), image=deployment['image'])
    (ROOT / 'data/artifacts/acceptance/server-logging.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
