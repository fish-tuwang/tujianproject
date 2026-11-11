"""Exercise real nginx limits on isolated loopback ports with a dummy upstream."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import http.client
import json
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import threading
import time
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.prepare_auth import ROOT, PROXY, mounts


class Upstream(BaseHTTPRequestHandler):
    def do_GET(self):
        status = 200
        if self.path == '/__defense_slow':
            time.sleep(3)
        elif self.path == '/__upstream_busy':
            status = 429
        elif self.path.startswith('/api/auth/login'):
            status = 405
        elif self.path.startswith('/api/'):
            status = 401
        self.send_response(status)
        if self.path == '/__upstream_busy':
            self.send_header('Retry-After', '120')
        self.send_header('Content-Length', '2'); self.end_headers(); self.wfile.write(b'{}')

    def log_message(self, *args):
        pass


class Connection(http.client.HTTPSConnection):
    def __init__(self, source):
        super().__init__('117.72.11.77', 18443, timeout=20, context=ssl.create_default_context())
        self.source = source

    def connect(self):
        sock = socket.create_connection(('127.0.0.1', 18443), timeout=20, source_address=(self.source, 0))
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def requests(path, count=1, workers=1, source='127.0.0.10', agent='Mozilla/5.0 Chrome/140.0', spoof=False):
    def batch(size):
        output = []
        with closing(Connection(source)) as client:
            for index in range(size):
                headers = {'Host': '117.72.11.77', 'User-Agent': agent}
                if spoof:
                    headers['X-Forwarded-For'] = '198.51.100.' + str(index % 240 + 1)
                client.request('GET', path, headers=headers)
                response = client.getresponse()
                output.append({'status': response.status, 'retry': response.getheader('Retry-After'), 'robots': response.getheader('X-Robots-Tag'), 'body': response.read().decode()})
        return output
    with ThreadPoolExecutor(max_workers=workers) as pool:
        groups = list(pool.map(batch, [count // workers + (i < count % workers) for i in range(workers)]))
    return [row for group in groups for row in group]


def main():
    folder = ROOT / 'data/artifacts/acceptance' / ('defense-shadow-' + uuid4().hex[:8])
    folder.mkdir(mode=0o700)
    logs = folder / 'logs'; logs.mkdir()
    server = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    image = subprocess.check_output(['docker', 'inspect', '--format', '{{.Image}}', PROXY], text=True).strip()
    config = (ROOT / 'app/deploy/preview-nginx.conf').read_text()
    config = config.replace('listen 80;', 'listen 127.0.0.1:18080;').replace('listen 443 ssl;', 'listen 127.0.0.1:18443 ssl;')
    config = config.replace('http://127.0.0.1:8092', 'http://127.0.0.1:' + str(server.server_port))
    config = config.replace('        location = /robots.txt {', '        location = /__defense_slow { proxy_pass http://127.0.0.1:' + str(server.server_port) + '; }\n        location = /robots.txt {')
    path = folder / 'nginx.conf'; path.write_text(config)
    mount_args = mounts(path)
    mount_args = [str(logs) + ':/var/log/dual-catalog' if value == str(ROOT / 'data/artifacts/logs') + ':/var/log/dual-catalog' else value for value in mount_args]
    name = 'dual-catalog-defense-' + uuid4().hex[:8]
    cid = None
    report = {'status': 'fail', 'scope': 'isolated real nginx; dummy upstream; loopback only', 'checks': [], 'limits': {}}
    def check(label, passed):
        if not passed:
            raise AssertionError(label)
        report['checks'].append(label); print('PASS ' + label, flush=True)
    try:
        cid = subprocess.check_output(['docker', 'run', '-d', '--name', name, '--network', 'host', '--memory', '128m', '--pids-limit', '128', *mount_args, image], text=True).strip()
        for _ in range(50):
            try:
                robots = requests('/robots.txt')[0]
                break
            except (OSError, http.client.HTTPException):
                time.sleep(.1)
        else:
            raise RuntimeError('isolated proxy did not start')
        check('robots disallows the complete site and headers prohibit indexing', robots['status'] == 200 and robots['body'] == 'User-agent: *\nDisallow: /\n' and 'noindex' in robots['robots'])
        check('known crawler is rejected while browser requests pass', requests('/login/', agent='Googlebot/2.1')[0]['status'] == 403 and requests('/login/')[0]['status'] == 200)
        check('WeChat and Sogou browsers pass while Sogou spider is rejected', all(requests('/login/', agent=agent)[0]['status'] == 200 for agent in ['Mozilla/5.0 MicroMessenger/8.0', 'Mozilla/5.0 SogouMobileBrowser/6.0']) and requests('/login/', agent='Sogou web spider/4.0')[0]['status'] == 403)
        check('upstream retry advice is preserved without a duplicate header', requests('/__upstream_busy')[0]['retry'] == '120')
        cases = [('login', '/api/auth/login', 12, 1, '127.0.0.2', 405), ('api', '/api/gunpla', 100, 12, '127.0.0.3', 401), ('images', '/api/reference-images/registered-example', 420, 12, '127.0.0.4', 401), ('connections', '/__defense_slow', 64, 64, '127.0.0.5', 200), ('global', '/unindexed-page', 1800, 12, '127.0.0.6', 200)]
        for key, route, count, workers, source, allowed in cases:
            rows = requests(route, count, workers, source, spoof=key == 'api')
            statuses = Counter(row['status'] for row in rows)
            report['limits'][key] = dict(statuses)
            check(key + ' returns 429 for excess and preserves admitted requests', statuses[429] > 0 and statuses[allowed] > 0 and set(statuses) <= {429, allowed})
            check(key + ' rejection includes retry advice', all(r['retry'] == '10' for r in rows if r['status'] == 429))
        events = [json.loads(line) for line in (logs / 'access.jsonl').read_text().splitlines()]
        check('spoofed forwarding headers do not change the client-IP bucket', all(e['client_ip'] == '127.0.0.3' for e in events if e['path'] == '/api/gunpla'))
        check('request and connection rejections are recorded in structured logs', any(e.get('request_limit') == 'REJECTED' for e in events) and any(e.get('connection_limit') == 'REJECTED' for e in events))
        errors = subprocess.check_output(['docker', 'logs', cid], stderr=subprocess.STDOUT, text=True)
        check('each intended limit zone rejects actual traffic', all(('zone "catalog_' + zone + '"') in errors for zone in ['login', 'api', 'images', 'clients', 'global']))
        report['status'] = 'pass'
    finally:
        if cid:
            log_output = subprocess.run(['docker', 'logs', cid], stderr=subprocess.STDOUT, stdout=subprocess.PIPE, text=True, check=False)
            (folder / 'nginx-errors.log').write_text(log_output.stdout)
            subprocess.run(['docker', 'rm', '-f', cid], check=True, capture_output=True)
        server.shutdown(); server.server_close()
        (ROOT / 'data/artifacts/acceptance/crawler-defense-shadow.json').write_text(json.dumps(report, indent=2))
    print(json.dumps({'status': report['status'], 'checks': len(report['checks']), 'limits': report['limits']}))


if __name__ == '__main__':
    main()
