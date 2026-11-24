"""Resume the captured official Tomica gallery through the installed publisher."""
import asyncio
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import date
import hashlib
import importlib
import inspect
from io import BytesIO
import json
from pathlib import Path
import re
import shutil
import threading
from types import SimpleNamespace
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

import httpx
from PIL import Image, ImageChops, ImageOps, ImageStat
from sqlalchemy import select

from .audit import audit
from .config import ROOT
from .models import SourceIdentity, TomicaModel, TomicaVariant
from .reference_images import image_type

INVENTORY = ROOT / 'backend/data/tomica-mall-inventory.json'
MAX_IMAGE = 20 * 1024 * 1024
SEED_FILE = ROOT / 'backend/data/tomica-image-seed.json'
SEED_IMAGES = json.loads(SEED_FILE.read_text(encoding='utf-8')) if SEED_FILE.exists() else {}
SEED_BASE = 'https://117.72.11.77/tomica-image-seed-20261124/'


def image_url(url):
    parts = urlsplit(url)
    if (parts.scheme != 'https' or parts.netloc != 'takaratomymall.jp'
            or not parts.path.startswith('/img/goods/') or parts.query or parts.fragment):
        raise ValueError('image outside recorded official source')
    return url


def valid_image(body):
    if len(body) > MAX_IMAGE:
        raise ValueError('image exceeds size limit')
    image_type(body[:32])
    with Image.open(BytesIO(body)) as image:
        image.verify()
    return body


def same_picture(thumbnail, original):
    with Image.open(BytesIO(thumbnail)) as small, Image.open(BytesIO(original)) as large:
        if large.width <= small.width or large.height <= small.height:
            return False
        if abs(small.width / small.height - large.width / large.height) > .03:
            return False
        a = ImageOps.exif_transpose(small).convert('RGB').resize((64, 64))
        b = ImageOps.exif_transpose(large).convert('RGB').resize((64, 64))
        return sum(ImageStat.Stat(ImageChops.difference(a, b)).mean) / 3 < 4


def download(url, directory, client):
    image_url(url)
    path = directory / (hashlib.sha256(url.encode()).hexdigest() + '.image')
    if path.exists():
        return path, valid_image(path.read_bytes())
    expected = SEED_IMAGES.get(url)
    fetch_url = SEED_BASE + expected + '.image' if expected and re.fullmatch(r'[a-f0-9]{64}', expected) else url
    with client.stream('GET', fetch_url) as response:
        response.raise_for_status()
        if not expected and not response.headers.get('content-type', '').startswith('image/'):
            raise ValueError('source did not return an image')
        chunks, size = [], 0
        for chunk in response.iter_bytes():
            size += len(chunk)
            if size > MAX_IMAGE:
                raise ValueError('image exceeds size limit')
            chunks.append(chunk)
    body = valid_image(b''.join(chunks))
    if expected and hashlib.sha256(body).hexdigest() != expected:
        raise ValueError('official cache seed checksum mismatch')
    temporary = path.with_suffix('.tmp')
    temporary.write_bytes(body)
    temporary.replace(path)
    return path, body


def prepare_image(url, packaging, old_packaging, directory, client, alternatives=(), product_url=None):
    source_url = image_url(url)
    path, body = download(url, directory, client)
    if '/img/goods/6/' in url:
        matched = next((image for image in alternatives if same_picture(body, (directory / image['path']).read_bytes())), None)
        if matched:
            path = directory / matched['path']
            body = path.read_bytes()
            source_url = matched['url']
        else:
            # This native thumbnail/original pair was observed on the product page.
            # A successful URL alone is insufficient: the pictures must also match.
            original_url = url.replace('/img/goods/6/', '/img/goods/5/', 1)
            try:
                original_path, original = download(original_url, directory, client)
                matched = same_picture(body, original)
            except httpx.HTTPStatusError as error:
                if error.response.status_code != 404:
                    raise
                matched = False
            if not matched and product_url:
                # Some official pages use different filenames for thumbnail and original.
                # Read the actual gallery anchors instead of inventing filename variants.
                parts = urlsplit(product_url)
                if parts.scheme != 'https' or parts.netloc != 'takaratomymall.jp' or not re.fullmatch(r'/shop/g/g[0-9]{13}/', parts.path):
                    raise ValueError('invalid official product page')
                response = client.get(product_url)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, 'html.parser')
                for anchor in soup.select('main a[rel="shadowbox[group]"]'):
                    candidate = image_url(urljoin(product_url, anchor.get('href', '')))
                    candidate_path, candidate_body = download(candidate, directory, client)
                    if same_picture(body, candidate_body):
                        original_path, original, original_url = candidate_path, candidate_body, candidate
                        matched = True
                        break
            if not matched:
                raise ValueError('official original does not match its listed thumbnail')
            path, body, source_url = original_path, original, original_url
    digest = hashlib.sha256(body).hexdigest()
    return {'url': source_url, 'listed_url': url, 'path': path.name,
            'sha256': digest, 'status': 'downloaded',
            'kind': 'packaging' if packaging or digest in old_packaging else 'gallery'}


def official_cache(app, collector):
    with app.state.session_factory() as session:
        entry = session.scalar(select(SourceIdentity).where(
            SourceIdentity.source == collector.SOURCE, SourceIdentity.kind == 'product',
            SourceIdentity.needs_review.is_(False)))
        if entry is None or not entry.evidence.get('images'):
            raise ValueError('existing official image cache is not available')
        digest = entry.evidence['images'][0]['sha256']
    response = collector.image(digest, SimpleNamespace(app=app))
    if inspect.isawaitable(response):
        response = asyncio.run(response)
    path = getattr(response, 'path', None)
    if path and Path(path).is_file():
        return Path(path).resolve().parent
    directory = Path(app.state.settings.artifact_dir)
    directory = directory if directory.is_absolute() else ROOT / directory
    base = directory.parent if directory.name == 'acceptance' else directory
    matches = list(base.rglob(digest + '.image'))
    if len(matches) != 1:
        raise ValueError('official cache location is ambiguous')
    return matches[0].resolve().parent


def list_packaging_covers(value, session):
    """Change list covers only; preserve the full car/detail gallery."""
    if not isinstance(value, dict) or not value.get('items'):
        return value
    try:
        from .tomica_official import SOURCE
    except ImportError:
        return value
    rows = {row['id']: row for row in value['items']}
    entries = session.scalars(select(SourceIdentity).where(
        SourceIdentity.source == SOURCE, SourceIdentity.kind == 'product',
        SourceIdentity.needs_review.is_(False), SourceIdentity.entity_id.in_(rows)))
    selected = set()
    for entry in entries:
        product = entry.evidence
        if entry.entity_id in selected or product.get('packaging_status') != 'verified':
            continue
        picture = next((i for i in product.get('images', []) if i.get('kind') == 'packaging'), None)
        if picture and re.fullmatch(r'[a-f0-9]{64}', picture.get('sha256', '')):
            rows[entry.entity_id].update(image_url=None, source_image_url=None,
                preview_image_url='/api/tomica/official-images/' + picture['sha256'],
                image_status='ready', image_attribution='TAKARA TOMY')
            selected.add(entry.entity_id)
    return value


class GalleryBackfill:
    def __init__(self, app, collector):
        self.app, self.collector = app, collector
        directory = Path(app.state.settings.artifact_dir)
        directory = directory if directory.is_absolute() else ROOT / directory
        self.directory = directory / 'tomica-mall-backfill'
        self.stop = threading.Event()
        self.lock = threading.RLock()
        self.state = {'status': 'starting', 'processed': 0}
        self.thread = threading.Thread(target=self.run, name='tomica-official-backfill', daemon=True)

    def snapshot(self):
        with self.lock:
            return json.loads(json.dumps(self.state))

    def save(self, **fields):
        with self.lock:
            self.state.update(fields)
            temporary = self.directory / 'state.tmp'
            temporary.write_text(json.dumps(self.state, ensure_ascii=False), encoding='utf-8')
            temporary.replace(self.directory / 'state.json')

    def document(self, raw, existing):
        snapshot = dict(raw)
        snapshot['text'] = raw.get('text', '')
        snapshot['images'] = []
        document = self.collector.parse_snapshot(snapshot)
        release = re.search(r'\u767a\u58f2\u65e5\s*[:\uff1a]\s*(\d{4})\u5e74(\d{1,2})\u6708(\d{1,2})\u65e5', snapshot['text'])
        if release:
            document['release_date'] = date(*map(int, release.groups())).isoformat()
        if existing:
            previous = existing.evidence
            if previous.get('jan') != raw['jan'] or previous.get('source_url') != raw['source_url']:
                raise ValueError('existing product barcode/source mismatch')
            old, new = previous['name'], raw['name']
            if self.collector.canonical_name(old) != self.collector.canonical_name(new):
                a, b = re.search(r'No\.?\s*(\d+)', old, re.I), re.search(r'No\.?\s*(\d+)', new, re.I)
                if '\ufffd' not in old or not (a and b and int(a[1]) == int(b[1])):
                    raise ValueError('official product name changed; review required')
                # Repair only the damaged official label of the same barcode/number.
                existing.evidence = dict(previous, name=new)
            document['eligibility'] = 'accepted'
            document['eligibility_reason'] = previous.get('eligibility_reason') or 'previously verified same official barcode'
            document['release_date'] = document.get('release_date') or previous.get('release_date')
            document['metadata_source_url'] = raw['source_url']
        return document

    def publish_one(self, raw, images_directory, cache_directory, client, pool):
        with self.app.state.session_factory() as session:
            existing = session.scalar(select(SourceIdentity).where(
                SourceIdentity.source == self.collector.SOURCE, SourceIdentity.kind == 'product',
                SourceIdentity.source_key == raw['jan']))
            previous = json.loads(json.dumps(existing.evidence)) if existing else {}
            if existing:
                backup = self.directory / 'backups' / (raw['jan'] + '.json')
                if not backup.exists():
                    backup.write_text(json.dumps({'model_id': existing.entity_id, 'evidence': previous}, ensure_ascii=False), encoding='utf-8')
            document = self.document(raw, existing)
            if document.get('eligibility') != 'accepted':
                return {'action': document.get('eligibility', 'review'), 'jan': raw['jan'], 'name': raw['name'],
                        'reason': document.get('eligibility_reason', 'material unverified')}
            old_packaging = {i['sha256'] for i in previous.get('images', []) if i.get('kind') == 'packaging'}
            verified = set(raw.get('verified_packaging_images', []))
            futures = [pool.submit(prepare_image, url, url in verified, old_packaging, images_directory, client) for url in raw['images'] if '/img/goods/6/' not in url]
            wait(futures)
            images = [future.result() for future in futures]
            for url in raw['images']:
                if '/img/goods/6/' in url:
                    images.append(prepare_image(url, url in verified, old_packaging, images_directory, client, images, raw['source_url']))
            unique = {}
            for image in images:
                old_image = unique.get(image['sha256'])
                if old_image and old_image['kind'] == 'packaging':
                    image['kind'] = 'packaging'
                unique[image['sha256']] = image
            # Retain every previously published photo and variant association.
            for old_image in previous.get('images', []):
                if old_image['sha256'] in unique:
                    continue
                path = cache_directory / (old_image['sha256'] + '.image')
                body = valid_image(path.read_bytes())
                if hashlib.sha256(body).hexdigest() != old_image['sha256']:
                    raise ValueError('previous official image checksum mismatch')
                retained = images_directory / ('retained-' + path.name)
                if not retained.exists():
                    shutil.copy2(path, retained)
                unique[old_image['sha256']] = dict(old_image, path=retained.name, status='downloaded')
            document['images'] = list(unique.values())
            document['packaging_status'] = 'verified' if any(i['kind'] == 'packaging' for i in document['images']) else 'unverified'
            review = None
            if existing:
                model = session.get(TomicaModel, existing.entity_id)
                review = {'model_id': model.id, 'model_name': model.name_original, 'source_name': document['name']}
                if previous.get('variant_id'):
                    variant = session.get(TomicaVariant, previous['variant_id'])
                    if variant is None or variant.model_id != model.id:
                        raise ValueError('previous variant association is invalid')
                    review.update(variant_id=variant.id, variant_code=variant.variant_code)
            result = self.collector.publish(session, document, images_directory, cache_directory, review=review)
            if result['action'] in {'created', 'supplemented', 'unchanged'}:
                session.commit()
            else:
                session.rollback()
            return dict(result, jan=raw['jan'], name=raw['name'], image_count=len(document['images']),
                        packaging=document['packaging_status'] == 'verified')

    def run(self):
        try:
            import fcntl
            self.directory.mkdir(parents=True, exist_ok=True)
            with (self.directory / 'lock').open('a') as lease:
                try:
                    fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    self.state = {'status': 'another_worker_running'}
                    return
                self.collect()
        except Exception as error:
            self.state.update(status='failed', error=type(error).__name__ + ': ' + str(error))
            try:
                self.save()
            except OSError:
                pass
            audit('tomica_official_backfill_failed', error=type(error).__name__)

    def collect(self):
        body = INVENTORY.read_bytes()
        version = hashlib.sha256(body + (SEED_FILE.read_bytes() if SEED_FILE.exists() else b'')).hexdigest()
        saved = self.directory / 'state.json'
        old = json.loads(saved.read_text(encoding='utf-8')) if saved.exists() else {}
        if old.get('version') == version and old.get('status') in {'succeeded', 'completed_with_review'}:
            self.state = old
            return
        inventory = json.loads(body)
        cache_directory = official_cache(self.app, self.collector)
        images_directory = self.directory / 'images'
        images_directory.mkdir(exist_ok=True)
        (self.directory / 'backups').mkdir(exist_ok=True)
        with self.app.state.session_factory() as session:
            known = set(session.scalars(select(SourceIdentity.source_key).where(
                SourceIdentity.source == self.collector.SOURCE, SourceIdentity.kind == 'product')))
        rows = sorted(inventory['products'], key=lambda p: p['jan'] not in known)
        counts = {'created': 0, 'supplemented': 0, 'unchanged': 0, 'excluded': 0, 'review': 0, 'failed': 0}
        results, packaging = [], 0
        self.save(status='running', version=version, total=len(rows), processed=0, counts=counts, reviews=[], failures=[])
        audit('tomica_official_backfill_started', products=len(rows), image_references=sum(len(p['images']) for p in rows))
        with httpx.Client(timeout=20, follow_redirects=False, limits=httpx.Limits(max_connections=4),
                          headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://takaratomymall.jp/'}) as client, ThreadPoolExecutor(max_workers=4) as pool:
            for row in rows:
                if self.stop.is_set():
                    self.save(status='interrupted')
                    return
                for attempt in range(3):
                    try:
                        result = self.publish_one(row, images_directory, cache_directory, client, pool)
                        break
                    except (httpx.TransportError, OSError) as error:
                        if attempt < 2 and not self.stop.wait(2 ** attempt):
                            continue
                        result = {'action': 'failed', 'jan': row['jan'], 'name': row['name'], 'reason': type(error).__name__ + ': ' + str(error)}
                    except Exception as error:
                        result = {'action': 'failed', 'jan': row['jan'], 'name': row['name'], 'reason': type(error).__name__ + ': ' + str(error)}
                    break
                action = result['action']
                if action not in counts:
                    action = 'review'
                counts[action] += 1
                results.append(result)
                packaging += bool(result.get('packaging') and action in {'created', 'supplemented', 'unchanged'})
                self.save(processed=len(results), counts=counts, packaging_products=packaging,
                          reviews=[r for r in results if r['action'] == 'review'], failures=[r for r in results if r['action'] == 'failed'])
                audit('tomica_official_backfill_item', jan=row['jan'], action=action, images=result.get('image_count', 0))
        (self.directory / 'results.json').write_text(json.dumps(results, ensure_ascii=False), encoding='utf-8')
        status = 'succeeded' if not counts['failed'] and not counts['review'] else 'completed_with_review' if not counts['failed'] else 'incomplete'
        self.save(status=status)
        audit('tomica_official_backfill_finished', **counts, packaging_products=packaging)


def start(app):
    try:
        collector = importlib.import_module('backend.app.tomica_official')
    except ModuleNotFoundError as error:
        if error.name == 'backend.app.tomica_official':
            return None
        raise
    job = GalleryBackfill(app, collector)
    app.state.tomica_backfill = job
    job.thread.start()
    return job
