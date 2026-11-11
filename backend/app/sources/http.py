from datetime import datetime, timezone
import hashlib
import time
from urllib.parse import parse_qsl, quote, unquote, unquote_to_bytes, urlencode, urljoin, urlsplit, urlunsplit
import re
from urllib.robotparser import RobotFileParser
import httpx
from backend.app.sources.base import FetchResult

MAX_HTML = 8 * 1024 * 1024
AGENT = 'DualCatalog/0.1 (+personal catalog; limited serial requests)'


def normalize_url(base: str, href: str, source: str) -> str:
    parts = urlsplit(urljoin(base, href.strip()))
    if source == 'gunpla':
        path = unquote(parts.path)
        listing = re.fullmatch(r'/index/index/(brand|series)/cate/[1-9][0-9]*', path)
        valid = path in {'/gunpla', '/schedule'} or listing or re.fullmatch(r'/index/index/detail/id/[1-9][0-9]*', path)
        if parts.scheme != 'https' or parts.hostname != 'bandaihobbysite.cn' or parts.username or parts.password or parts.port or parts.fragment or not valid or '\\' in path or '\x00' in path:
            raise ValueError('URL outside gunpla source boundary')
        pairs = parse_qsl(parts.query, keep_blank_values=True)
        if len({key for key, _ in pairs}) != len(pairs) or any(key not in {'page', 'tag'} or not listing or not re.fullmatch(r'[1-9][0-9]{0,3}', value) or (key == 'tag' and value not in {'1', '2', '3', '4'}) for key, value in pairs):
            raise ValueError('invalid gunpla query')
        return urlunsplit(('https', 'bandaihobbysite.cn', path, urlencode(sorted(pairs)), ''))
    expected = ('http', 'tomica.minibird.jp') if source == 'tomica' else ('https', 'wiki.52poke.com')
    raw_path = unquote_to_bytes(parts.path)
    try:
        path = raw_path.decode('utf-8')
    except UnicodeDecodeError:
        path = raw_path.decode('cp932') if source == 'tomica' else raw_path.decode('utf-8')
    prefixes = ('/t-tomica/',) if source == 'tomica' else ('/wiki/', '/zh-hans/')
    if (parts.scheme, parts.hostname) != expected or parts.username or parts.password or parts.port or not path.startswith(prefixes):
        raise ValueError('URL outside source boundary')
    if any(p == '..' for p in path.split('/')) or '\\' in path or '\x00' in path:
        raise ValueError('invalid URL path')
    if parts.query:
        raise ValueError('query URL not allowed')
    return urlunsplit((parts.scheme, parts.netloc, quote(path, safe='/()_-.,&:!', encoding='cp932' if source == 'tomica' else 'utf-8'), '', quote(unquote(parts.fragment), safe='_-')))


class SourceHttpClient:
    def __init__(self, source, *, transport=None, interval=2, clock=time.monotonic, sleep=time.sleep):
        self.source, self.interval, self.clock, self.sleep = source, max(2, interval), clock, sleep
        self.client = httpx.Client(timeout=20, headers={'User-Agent': AGENT}, transport=transport, follow_redirects=False)
        self.last_request = None
        self.robots = None
        self.robots_loaded = False

    def close(self):
        self.client.close()

    def _request(self, url, headers=None):
        if self.last_request is not None:
            self.sleep(max(0, self.interval - (self.clock() - self.last_request)))
        self.last_request = self.clock()
        with self.client.stream('GET', url, headers=headers) as response:
            chunks, size = [], 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > MAX_HTML:
                    raise ValueError('HTML size limit exceeded')
                chunks.append(chunk)
            response._content = b''.join(chunks)
            return response

    def _load_robots(self, url):
        if self.robots_loaded:
            return
        parts = urlsplit(url)
        robot_url = urlunsplit((parts.scheme, parts.netloc, '/robots.txt', '', ''))
        response = self._request(robot_url)
        if response.status_code == 404:
            self.robots_loaded = True
            return
        if response.status_code != 200:
            raise ValueError('robots policy unavailable')
        self.robots = RobotFileParser()
        self.robots.parse(response.text.splitlines())
        self.robots_loaded = True

    def fetch(self, url, etag=None, last_modified=None, previous_hash=None):
        result = FetchResult(url=url, checked_at=datetime.now(timezone.utc))
        try:
            url = normalize_url(url, url, self.source).split('#')[0]
            self._load_robots(url)
            headers = {}
            if etag:
                headers['If-None-Match'] = etag
            if last_modified:
                headers['If-Modified-Since'] = last_modified
            for attempt in range(3):
                try:
                    current = url
                    for redirects in range(4):
                        if self.robots and not self.robots.can_fetch(AGENT, current):
                            raise ValueError('ROBOTS_DISALLOWED')
                        response = self._request(current, headers)
                        if response.status_code not in {301, 302, 303, 307, 308}:
                            break
                        if redirects == 3:
                            raise ValueError('redirect limit exceeded')
                        current = normalize_url(current, response.headers.get('location', ''), self.source).split('#')[0]
                    result.final_url, result.status = current, response.status_code
                    result.headers = dict(response.headers)
                    if response.status_code == 304:
                        result.not_modified = True
                        return result
                    if response.status_code == 429 or response.status_code >= 500:
                        try:
                            delay = max(2 ** (attempt + 1), float(response.headers.get('retry-after', '0')))
                        except ValueError:
                            delay = 2 ** (attempt + 1)
                        result.retry_after = delay
                        if delay > 300 or attempt == 2:
                            raise ValueError('HTTP_' + str(response.status_code))
                        self.sleep(delay)
                        continue
                    if response.status_code != 200:
                        raise ValueError('HTTP_' + str(response.status_code))
                    result.content_hash = hashlib.sha256(response.content).hexdigest()
                    result.not_modified = result.content_hash == previous_hash
                    result.body = b'' if result.not_modified else response.content
                    result.etag = response.headers.get('etag')
                    result.last_modified = response.headers.get('last-modified')
                    return result
                except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as error:
                    if attempt == 2:
                        raise error
                    self.sleep(2 ** (attempt + 1))
        except (ValueError, httpx.HTTPError) as error:
            result.error = str(error)
        return result
