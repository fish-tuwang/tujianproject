"""Incremental China official new-arrival checks and monthly news publication."""
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
import threading
import time
from urllib.parse import quote, unquote, urljoin, urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo

from apscheduler.triggers.interval import IntervalTrigger
from bs4 import BeautifulSoup
import httpx
from sqlalchemy import select

from .audit import audit
from .config import ROOT
from .models import TomicaNews, now
from .repository import CatalogRepository
from .tomica_mall_backfill import download, image_url

BASELINE = ROOT / 'backend/data/tomica-cn-baseline.json'
ROOTS = ['https://www.tomy.cn/tomica_item/item', 'https://www.tomy.cn/tomytec_item/item']
ZONE = ZoneInfo('Asia/Shanghai')


def trigger():
    return IntervalTrigger(days=2, start_date=datetime(2026, 1, 1, 3, tzinfo=ZONE), timezone=ZONE)


def source_url(base, href):
    parsed = urlsplit(urljoin(base, href))
    path = unquote(parsed.path).rstrip('/')
    if (parsed.scheme != 'https' or parsed.netloc != 'www.tomy.cn' or parsed.query or parsed.fragment
            or not re.fullmatch(r'/(?:tomica|tomytec)(?:_item/[^/]+(?:/page/[1-9][0-9]*)?|/item/[^/]+/[^/]+)', path)):
        raise ValueError('outside China official catalogue')
    return 'https://www.tomy.cn' + quote(path, safe='/_-.,()')


def listing_page(url, html):
    soup = BeautifulSoup(html, 'html.parser')
    pages, products = set(), {}
    for anchor in soup.select('a[href]'):
        try:
            target = source_url(url, anchor['href'])
        except ValueError:
            continue
        path = urlsplit(target).path
        if re.fullmatch(r'/(?:tomica|tomytec)_item/[^/]+', path):
            pages.add(target)
        elif '/page/' in path and anchor.find_parent(class_='pagination'):
            pages.add(target)
        elif '/item/' in path and anchor.find('h3'):
            image = anchor.find('img', src=True)
            products[target] = {'name': anchor.find('h3').get_text(' ', strip=True),
                               'cover': urljoin(url, image['src']) if image else None}
    return pages, products


def product_page(url, html):
    soup = BeautifulSoup(html, 'html.parser')
    heading = soup.select_one('h2.l-product-detail')
    if heading is None:
        raise ValueError('official product heading missing')
    properties = {node.dt.get_text(' ', strip=True).rstrip('：:'): node.dd.get_text(' ', strip=True)
                  for node in soup.select('ul.table.l-product-detail dl') if node.dt and node.dd}
    images = list(dict.fromkeys(urljoin(url, img['src']) for img in
                               soup.select('.js-image img[src],.js-thumbnails img[src]')))
    for url_image in images:
        if urlsplit(image_url(url_image)).netloc != 'www.tomy.cn':
            raise ValueError('product photo outside China source')
    metadata = {}
    for name in ('published', 'modified'):
        node = soup.find('meta', property='article:' + name + '_time')
        value = node.get('content') if node else None
        metadata[name + '_at'] = datetime.fromisoformat(value).astimezone(ZONE).isoformat() if value else None
    category = soup.select_one('.l-btns a[href*="_item/"]')
    return {'source_url': source_url(url, url), 'name': heading.get_text(' ', strip=True),
            'properties': properties, 'images': images, 'category': category.get_text(' ', strip=True) if category else '',
            **metadata}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def atomic_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)


def storage(settings):
    directory = Path(settings.artifact_dir)
    return (directory if directory.is_absolute() else ROOT / directory) / 'tomica-cn-sync'


class ChinaSync:
    def __init__(self, app):
        self.app = app
        self.directory = storage(app.state.settings)
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.lock = threading.Lock()
        self.pending = None
        self.running = False
        report = self.directory / 'last-run.json'
        self.state = json.loads(report.read_text(encoding='utf-8')) if report.exists() else {'status': 'idle'}
        if self.state['status'] in {'running', 'queued'}:
            self.state['status'] = 'interrupted'
        self.thread = threading.Thread(target=self.loop, name='tomica-cn-schedule', daemon=True)

    def snapshot(self):
        with self.lock:
            return dict(self.state, interval_hours=48, timezone='Asia/Shanghai',
                        enabled=self.thread.is_alive(),
                        next_run_at=trigger().get_next_fire_time(None, datetime.now(ZONE)).isoformat())

    def submit(self, reason='manual'):
        with self.lock:
            if self.running or self.pending:
                return {'status': 'already_running', 'run_id': self.state.get('run_id')}
            self.pending = (str(uuid4()), reason)
            run_id = self.pending[0]
            self.state = dict(self.state, run_id=self.pending[0], status='queued', reason=reason)
        self.wake.set()
        return {'status': 'queued', 'run_id': run_id}

    def save(self, **fields):
        with self.lock:
            self.state.update(fields)
            atomic_json(self.directory / 'last-run.json', self.state)

    def loop(self):
        completed = self.state.get('completed_at')
        due = trigger().get_next_fire_time(None, datetime.fromisoformat(completed) + timedelta(microseconds=1)) if completed else None
        if due and due <= datetime.now(ZONE):
            self.submit('catchup')
        next_due = trigger().get_next_fire_time(None, datetime.now(ZONE))
        while not self.stop.is_set():
            with self.lock:
                pending = self.pending
                self.pending = None
                self.running = bool(pending)
            if pending:
                try:
                    self.run_once(*pending)
                except Exception as error:
                    with self.lock:
                        self.state.update(status='failed', error=type(error).__name__ + ': ' + str(error))
                    audit('tomica_cn_sync_failed', run_id=pending[0], error=type(error).__name__)
                finally:
                    with self.lock:
                        self.running = False
                next_due = trigger().get_next_fire_time(None, datetime.now(ZONE) + timedelta(microseconds=1))
            elif datetime.now(ZONE) >= next_due:
                self.submit('scheduled')
                continue
            self.wake.wait(1)
            self.wake.clear()

    def get(self, client, url):
        if self.stop.wait(max(0, self.app.state.settings.source_interval_seconds - (time.monotonic() - getattr(self, 'last_request', 0)))):
            raise RuntimeError('collection stopped')
        self.last_request = time.monotonic()
        def read():
            with client.stream('GET', url) as response:
                response.raise_for_status()
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > 8 * 1024 * 1024:
                        raise ValueError('official HTML exceeds size limit')
            return bytes(body).decode('utf-8-sig')
        return self.retry(read)

    def retry(self, action):
        for attempt in range(3):
            try:
                return action()
            except (httpx.TransportError, httpx.HTTPStatusError) as error:
                if isinstance(error, httpx.HTTPStatusError) and error.response.status_code not in {429, 500, 502, 503, 504}:
                    raise
                if attempt == 2 or self.stop.wait(2 ** (attempt + 1)):
                    raise

    def crawl(self, client, previous):
        queue, seen, listings = list(ROOTS), set(), {}
        while queue:
            url = queue.pop(0)
            if url in seen:
                continue
            if len(seen) >= 150:
                raise ValueError('catalogue pagination safety bound reached')
            pages, products = listing_page(url, self.get(client, url))
            seen.add(url)
            listings.update(products)
            queue.extend(p for p in sorted(pages) if p not in seen and p not in queue)
            self.save(phase='listing', listing_pages=len(seen), products_seen=len(listings))
        if not listings:
            raise ValueError('official listing is empty; baseline retained')
        homepage = BeautifulSoup(self.get(client, 'https://www.tomy.cn/tomica'), 'html.parser')
        latest = set()
        for anchor in homepage.select('a[href]'):
            try:
                url = source_url('https://www.tomy.cn/tomica', anchor['href'])
                if url in listings:
                    latest.add(url)
            except ValueError:
                pass
        targets = latest | {url for url, entry in listings.items() if previous.get(url, {}).get('listing') != entry}
        records = dict(previous)
        new, changed = [], []
        for index, url in enumerate(sorted(targets), 1):
            record = product_page(url, self.get(client, url))
            record['listing'] = listings[url]
            old = previous.get(url)
            if old is None:
                new.append(url)
            elif fingerprint(record) != fingerprint(old):
                changed.append(url)
            records[url] = record
            self.save(phase='details', details_checked=index)
        return records, listings, new, changed

    def publish_news(self, client, records, active, changed):
        dated = {url: row for url, row in records.items() if url in active and row.get('published_at') and row.get('name') and row.get('images')}
        latest_month = max((r['published_at'][:7] for r in dated.values()), default=None)
        published = 0
        images = self.directory / 'images'
        images.mkdir(exist_ok=True)
        with self.app.state.session_factory() as session:
            for url, record in dated.items():
                slug = 'cn-' + hashlib.sha256(url.encode()).hexdigest()[:24]
                existing = session.scalar(select(TomicaNews).where(TomicaNews.slug == slug))
                if not existing and record['published_at'][:7] != latest_month and url not in changed:
                    continue
                if existing and url not in changed:
                    continue
                photos = []
                for index, url_image in enumerate(record['images']):
                    if self.stop.is_set():
                        raise RuntimeError('collection stopped')
                    if self.stop.wait(max(0, self.app.state.settings.source_interval_seconds - (time.monotonic() - getattr(self, 'last_request', 0)))):
                        raise RuntimeError('collection stopped')
                    self.last_request = time.monotonic()
                    _, body = self.retry(lambda: download(url_image, images, client, refresh=url in changed, use_seed=False))
                    digest = hashlib.sha256(body).hexdigest()
                    target = images / (digest + '.jpg')
                    if not target.exists():
                        target.write_bytes(body)
                    cache = getattr(self.app.state, 'cache', None)
                    if cache is not None:
                        cache.set('news-image:' + digest, body, ttl=86400)
                    photos.append({'digest': digest, 'caption': '官网商品原图 ' + str(index + 1)})
                properties = record['properties']
                product = {'id': slug, 'number': properties.get('产品货号'), 'name': record['name'],
                           'name_zh': record['category'], 'cover_digest': photos[0]['digest'],
                           'summary': '中国官网上架：' + record['published_at'][:10],
                           'observations': [k + '：' + v for k, v in properties.items() if v], 'photos': photos}
                data = {'origin': 'official-cn', 'summary': product['summary'], 'products': [product]}
                digest = fingerprint(data)
                if existing and existing.content_hash == digest:
                    continue
                if existing is None:
                    existing = TomicaNews(slug=slug, archive_month=record['published_at'][:7],
                        title='中国官网新品 · ' + record['name'], source_name='TAKARA TOMY 中国官网',
                        source_url=url, content_hash=digest, data=data)
                    session.add(existing)
                else:
                    existing.archive_month = record['published_at'][:7]
                    existing.title = '中国官网新品 · ' + record['name']
                    existing.content_hash, existing.data, existing.updated_at = digest, data, now()
                published += 1
                self.save(phase='publishing', news_products=published)
            if self.stop.is_set():
                raise RuntimeError('collection stopped')
            if published:
                CatalogRepository(session).bump_revision('tomica-news')
            session.commit()
        return published

    def run_once(self, run_id, reason):
        import fcntl
        self.directory.mkdir(parents=True, exist_ok=True)
        with (self.directory / 'lock').open('a') as lease:
            try:
                fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return
            self.save(run_id=run_id, reason=reason, status='running', started_at=datetime.now(ZONE).isoformat(),
                      phase='listing', listing_pages=0, products_seen=0, details_checked=0, news_products=0,
                      new_products=0, changed_products=0, new_items=[], changed_items=[], error=None)
            audit('tomica_cn_sync_started', run_id=run_id, reason=reason)
            try:
                snapshot = self.directory / 'inventory.json'
                baseline = json.loads((snapshot if snapshot.exists() else BASELINE).read_text(encoding='utf-8'))
                with httpx.Client(timeout=25, follow_redirects=False, headers={'User-Agent': 'LittleAtlas/1.0 personal catalogue sync'}) as client:
                    records, active, new, changed = self.crawl(client, baseline['products'])
                    published = self.publish_news(client, records, active, set(new + changed))
                atomic_json(snapshot, {'products': records, 'checked_at': datetime.now(ZONE).isoformat()})
                self.save(status='completed', phase='complete', completed_at=datetime.now(ZONE).isoformat(),
                          new_products=len(new), changed_products=len(changed), news_products=published,
                          new_items=[{'name': records[u]['name'], 'source_url': u} for u in new],
                          changed_items=[{'name': records[u]['name'], 'source_url': u} for u in changed])
                audit('tomica_cn_sync_finished', run_id=run_id, new_products=len(new), changed_products=len(changed),
                      news_products=published, products_seen=len(active))
            except Exception as error:
                self.save(status='failed', phase='failed', error=type(error).__name__ + ': ' + str(error))
                audit('tomica_cn_sync_failed', run_id=run_id, error=type(error).__name__)


@asynccontextmanager
async def lifespan(app):
    if not hasattr(app.state, 'settings') or not hasattr(app.state, 'session_factory'):
        yield
        return
    job = ChinaSync(app)
    app.state.tomica_cn_sync = job
    job.thread.start()
    try:
        yield
    finally:
        job.stop.set()
        job.wake.set()
        job.thread.join(timeout=5)
