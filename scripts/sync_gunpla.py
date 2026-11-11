"""Serial official Gunpla synchronization with durable, atomic checkpoints."""
import argparse
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app.audit import audit, configure_audit
from backend.app.sources.http import SourceHttpClient
from backend.app.sources.gunpla import BASE, SALE_TYPES, is_model_product, parse_home, parse_listing, parse_product, unique

ROOT = Path(__file__).resolve().parents[1]


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    temporary.replace(path)


@contextmanager
def exclusive(directory):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / 'sync.lock').open('a+b') as stream:
        stream.seek(0); stream.write(b'0'); stream.flush(); stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


class GunplaCrawler:
    def __init__(self, directory, output=None, mode='incremental', limit=None, client=None, clock=time.time):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.output = Path(output) if output else self.directory / 'catalog.json'
        self.mode, self.limit, self.clock = mode, limit, clock
        self.client = client or SourceHttpClient('gunpla')
        self.manifest_path = self.directory / 'manifest.json'
        self.manifest = json.loads(self.manifest_path.read_text(encoding='utf-8')) if self.manifest_path.exists() else {}
        self.fetches = self.manifest.setdefault('fetches', {})
        self.products = self.manifest.setdefault('products', {})
        previous = self.manifest.get('coverage', {})
        self.started = previous.get('started_epoch', clock()) if previous.get('status') == 'running' and previous.get('mode') == mode else clock()
        self.coverage = {'status': 'running', 'complete': False, 'mode': mode, 'started_epoch': self.started, 'limited': limit is not None, 'brands': {}, 'excluded': [], 'pages_checked': 0, 'products_checked': 0}
        self.entries, self.errors, self.listings = [], [], {}
        self.last_checkpoint = 0

    def read(self, url, *, force=False, detail=False):
        key = hashlib.sha256(url.encode()).hexdigest()
        path = self.directory / 'html' / (key + '.html')
        previous = self.fetches.get(url, {})
        age = self.clock() - previous.get('fetched_at', 0)
        current_run = previous.get('fetched_at', 0) >= self.started
        fresh_incremental = self.mode == 'incremental' and age < (7 * 86400 if detail else 0)
        if path.exists() and (current_run or fresh_incremental) and not force:
            return path.read_bytes()
        result = self.client.fetch(url, etag=previous.get('etag'), last_modified=previous.get('last_modified'), previous_hash=previous.get('hash'))
        if result.error:
            raise ValueError(result.error)
        body = result.body or (path.read_bytes() if path.exists() else b'')
        if not body:
            raise ValueError('not-modified response without stored HTML')
        path.parent.mkdir(parents=True, exist_ok=True)
        if result.body:
            temporary = path.with_suffix('.tmp'); temporary.write_bytes(body); temporary.replace(path)
        self.fetches[url] = {'fetched_at': self.clock(), 'etag': result.etag or previous.get('etag'), 'last_modified': result.last_modified or previous.get('last_modified'), 'hash': hashlib.sha256(body).hexdigest()}
        return body

    def checkpoint(self, force=False):
        if not force and self.clock() - self.last_checkpoint < 15:
            return
        self.last_checkpoint = self.clock()
        self.coverage.update({'updated_at': datetime.now(timezone.utc).isoformat(), 'discovered_products': len(self.listings), 'stored_products': len(self.products), 'errors': len(self.errors)})
        self.manifest['coverage'] = self.coverage
        atomic_json(self.manifest_path, self.manifest)
        atomic_json(self.output, {'schema_version': 1, 'entries': self.entries + list(self.products.values()), 'coverage': self.coverage, 'errors': self.errors})
        print(json.dumps({key: self.coverage[key] for key in ['status', 'pages_checked', 'discovered_products', 'products_checked', 'stored_products', 'errors']}) , flush=True)

    def failure(self, stage, url, error):
        item = {'stage': stage, 'url': url, 'error': str(error)[:240]}
        self.errors.append(item)
        audit('page_failed', source='gunpla', **item)

    def collect_listing(self, url):
        parsed = parse_listing(url, self.read(url))
        self.coverage['pages_checked'] += 1
        for item in parsed['items']:
            key = item['official_id']
            old = self.listings.get(key)
            if old:
                for field in ['brand_ids', 'sale_types']:
                    old[field] = unique([*old[field], *item[field]])
            else:
                self.listings[key] = item
        self.checkpoint()
        return parsed['pages']

    def run(self):
        audit('run_started', source='gunpla', mode=self.mode)
        self.entries = parse_home(self.read(BASE + '/gunpla'))
        brands = [e for e in self.entries if e['kind'] == 'brand']
        series = {e['source_key'] for e in self.entries if e['kind'] == 'series'}
        self.checkpoint(True)
        for brand in brands:
            key = brand['source_key']
            groups = self.coverage['brands'][key] = {'name': brand['name'], 'groups': {}}
            for tag in [None, *SALE_TYPES]:
                base = BASE + '/index/index/brand/cate/' + key
                url = base + ('?' + urlencode({'tag': tag}) if tag else '')
                group = groups['groups'][tag or 'all'] = {'expected_pages': None, 'checked_pages': 0}
                try:
                    pages = self.collect_listing(url)
                    group['expected_pages'], group['checked_pages'] = pages, 1
                    for page in range(2, (min(pages, 1) if self.limit else pages) + 1):
                        query = {'page': page}
                        if tag:
                            query['tag'] = tag
                        try:
                            self.collect_listing(base + '?' + urlencode(sorted(query.items())))
                            group['checked_pages'] += 1
                        except Exception as error:
                            self.failure('listing', base + '?' + urlencode(sorted(query.items())), error)
                except Exception as error:
                    self.failure('listing', url, error)
        # Round-robin grades puts a representative of every official grade first.
        groups = defaultdict(list)
        for item in self.listings.values():
            groups[item['brand_ids'][0]].append(item)
        ordered = [items[index] for index in range(max((len(g) for g in groups.values()), default=0)) for items in groups.values() if index < len(items)]
        for listing in ordered:
            key, url = listing['official_id'], listing['source_url']
            allowed, reason = is_model_product({'name': listing['name'], 'data': listing}, series)
            if not allowed:
                self.products.pop(key, None)
                self.coverage['excluded'].append({'id': key, 'name': listing['name'], 'reason': reason})
                continue
            if self.limit is not None and self.coverage['products_checked'] >= self.limit:
                break
            signature = hashlib.sha256(json.dumps(listing, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            try:
                previous = self.products.get(key)
                changed = previous is not None and previous['data'].get('listing_signature') != signature
                entry = parse_product(url, self.read(url, detail=True, force=changed), listing)
                allowed, reason = is_model_product(entry, series)
                if allowed:
                    if not entry['data']['sale_types']:
                        raise ValueError('no verified official sale category')
                    entry['data']['listing_signature'] = signature
                    self.products[key] = entry
                else:
                    self.products.pop(key, None)
                    self.coverage['excluded'].append({'id': key, 'name': entry['name'], 'reason': reason})
                self.coverage['products_checked'] += 1
            except Exception as error:
                self.failure('detail', url, error)
            self.checkpoint()
        self.coverage['status'] = 'limited' if self.limit is not None else 'partial' if self.errors else 'complete'
        self.coverage['complete'] = self.coverage['status'] == 'complete'
        self.checkpoint(True)
        audit('run_finished', source='gunpla', status=self.coverage['status'], products=len(self.products), errors=len(self.errors))
        return json.loads(self.output.read_text(encoding='utf-8'))


def import_file(path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from backend.app.config import Settings
    from backend.app.gunpla import import_catalog
    settings = Settings()
    engine = create_engine(settings.database_url)
    try:
        with Session(engine) as session:
            changes = []
            report = import_catalog(session, json.loads(Path(path).read_text(encoding='utf-8')), changes=changes)
            session.commit()
            for change in changes:
                audit('record_' + change.pop('action'), source='gunpla', **change)
            print(json.dumps({'import': report}), flush=True)
            return 0 if not report['failed'] else 1
    finally:
        engine.dispose()


def warm_start(budget=180):
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session
    from backend.app.config import Settings
    from backend.app.cache import CatalogCache
    from backend.app.gunpla import GunplaQuery, GunplaRepository
    from backend.app.models import GunplaEntry, ImageAsset
    from backend.app.reference_images import cached_reference
    settings = Settings()
    engine = create_engine(settings.database_url)
    cache = CatalogCache(settings.redis_url.get_secret_value(), settings.cache_namespace)
    try:
        with Session(engine) as session:
            repo = GunplaRepository(session)
            ids = [r['preview_image_url'].rsplit('/', 1)[1] for r in repo.list_products(GunplaQuery(sale_type='1'))['items'] if r['preview_image_url']]
            ids += [r.data['logo_image_id'] for r in session.scalars(select(GunplaEntry).where(GunplaEntry.kind == 'brand')) if r.data.get('logo_image_id')]
            for key in ['3425', '3027']:
                detail = repo.product(key)
                if detail:
                    ids += [url.rsplit('/', 1)[1] for url in detail['gallery']]
            assets = [(key, session.get(ImageAsset, key).source_url) for key in dict.fromkeys(ids)]
        directory = Path(settings.artifact_dir).parent / 'reference-images'
        started = time.monotonic()
        report = {'ready': 0, 'failed': [], 'total': len(assets)}
        for key, url in assets:
            if time.monotonic() - started >= budget:
                break
            try:
                path, _ = cached_reference(key, url, directory)
                cache.set('image:' + key, path.read_bytes(), ttl=86400)
                report['ready'] += 1
            except Exception as error:
                report['failed'].append({'id': key, 'error': type(error).__name__})
        report['budget_exhausted'] = report['ready'] + len(report['failed']) < report['total']
        print(json.dumps({'warm_start': report}), flush=True)
        return 0
    finally:
        engine.dispose(); cache.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fetch-only', action='store_true')
    parser.add_argument('--import-file')
    parser.add_argument('--warm-start', action='store_true')
    parser.add_argument('--mode', choices=['full', 'incremental'], default='incremental')
    parser.add_argument('--directory', default=str(ROOT / 'artifacts/gunpla-source'))
    parser.add_argument('--output')
    parser.add_argument('--limit', type=int)
    args = parser.parse_args(argv)
    directory = Path(args.directory).resolve()
    if (ROOT / 'artifacts').resolve() not in directory.parents or (args.output and directory not in Path(args.output).resolve().parents) or (args.limit is not None and args.limit < 1):
        parser.error('use a positive limit and project artifact paths')
    configure_audit(directory.parent / 'logs', channels={'collection'})
    if args.warm_start:
        return warm_start()
    if args.import_file:
        return import_file(args.import_file)
    with exclusive(directory):
        crawler = GunplaCrawler(directory, args.output, args.mode, args.limit)
        try:
            document = crawler.run()
        finally:
            crawler.checkpoint(True)
            crawler.client.close()
        if not args.fetch_only:
            imported = import_file(crawler.output)
            if imported:
                return imported
        return 0 if document['coverage']['complete'] else 1


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
