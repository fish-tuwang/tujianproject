"""Proactively warm registered originals; resumable through the persistent disk cache."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
import time
from urllib.parse import urlsplit

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.cache import CatalogCache
from backend.app.config import Settings
from backend.app.models import GunplaEntry, ImageAsset
from backend.app.reference_images import image_type, read_reference, reference_path
from backend.app.gunpla_images import display_preview, PREVIEW_WIDTHS
from backend.app.repository import CatalogRepository


def build_manifest(session):
    repo = CatalogRepository(session)
    cars = sorted(repo.catalog_rows('tomica'), key=lambda r: (r['release_year'] or 99999, r['id']))
    pokemon = sorted(repo.catalog_rows('pokemon'), key=lambda r: r['dex'])
    covers = {row['primary_image_id'] for row in cars + pokemon if row['primary_image_id']}
    order = {row['primary_image_id']: index for index, row in enumerate(cars + pokemon)}
    gunpla = list(session.scalars(select(GunplaEntry).where(GunplaEntry.kind == 'product')))
    gunpla.sort(key=lambda row: (row.data.get('release_sort') or '', int(row.source_key)), reverse=True)
    for row in gunpla:
        image_id = row.data.get('cover_image_id')
        if image_id:
            covers.add(image_id)
            order.setdefault(image_id, len(order))
    groups = {}
    skipped = 0
    for asset in session.scalars(select(ImageAsset).execution_options(yield_per=500)):
        url = repo.image(asset.id)['source_image_url']
        if not url:
            skipped += 1
            continue
        group = groups.setdefault(url, {'url': url, 'ids': [], 'cover': False, 'order': len(order)})
        group['ids'].append(asset.id)
        group['cover'] |= asset.id in covers
        group['order'] = min(group['order'], order.get(asset.id, len(order)))
    images = sorted(groups.values(), key=lambda g: (not g['cover'], g['order'], g['url']))
    details = ['/api/tomica/' + row['id'] for row in cars] + ['/api/pokemon/' + str(row['dex']) for row in pokemon]
    details += ['/api/gunpla/products/' + row.source_key for row in gunpla]
    return images, details, skipped


def warm_group(group, client, base, directory, cache):
    data = None
    for asset_id in group['ids']:
        data = read_reference(asset_id, group['url'], directory)
        if data is not None:
            break
    origin = 'disk'
    if data is None:
        response = client.get(base + '/api/reference-images/' + group['ids'][0])
        response.raise_for_status()
        if not response.headers.get('content-type', '').startswith('image/'):
            raise ValueError('not an image')
        data = response.content
        image_type(data)
        origin = response.headers.get('x-catalog-cache', 'api')
    if urlsplit(group['url']).hostname == 'staticcdn.bandaihobbysite.cn':
        for width in PREVIEW_WIDTHS:
            display_preview(data, width, directory.parent / 'gunpla-previews')
    for asset_id in group['ids']:
        target = reference_path(asset_id, group['url'], directory)
        if read_reference(asset_id, group['url'], directory) is None:
            temporary = target.with_suffix('.warm.tmp')
            temporary.write_bytes(data)
            temporary.replace(target)
        cache.set('image:' + asset_id, data, ttl=86400)
    return origin


def warm_images(groups, client, base, directory, cache, report, publish):
    directory.mkdir(parents=True, exist_ok=True)
    by_host = {}
    for group in groups:
        by_host.setdefault(urlsplit(group['url']).hostname, []).append(group)
    lock = threading.Lock()
    stopped = threading.Event()

    def consume(rows):
        for group in rows:
            if stopped.is_set():
                return
            try:
                origin = warm_group(group, client, base, directory, cache)
                error = None
            except (httpx.HTTPError, ValueError, OSError) as exc:
                if isinstance(exc, httpx.TransportError) or (isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in {429, 500, 503, 504}):
                    stopped.set()
                    raise
                origin = None
                error = {'asset_id': group['ids'][0], 'error': type(exc).__name__}
            with lock:
                report['processed'] += 1
                if error:
                    report['failed'] += 1
                    if len(report['errors']) < 100:
                        report['errors'].append(error)
                else:
                    report['ready_images'] += len(group['ids'])
                    report['ready_unique_images'] += 1
                    report['ready_covers'] += int(group['cover'])
                    report['origins'][origin] = report['origins'].get(origin, 0) + 1
                if report['processed'] % 25 == 0 or report['processed'] == len(groups):
                    publish(report)

    # Requests go through the API's existing per-source 2-second limiter.
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(consume, by_host.values()))


def warm_once(settings, base):
    cache = CatalogCache(settings.redis_url.get_secret_value(), settings.cache_namespace)
    engine = create_engine(settings.database_url)
    report_path = Path(settings.artifact_dir) / 'cache-warmup.json'
    report_path.parent.mkdir(parents=True, exist_ok=True)

    def publish(value):
        value['updated_at'] = datetime.now(timezone.utc).isoformat()
        temporary = report_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(report_path)
        print(json.dumps({k: v for k, v in value.items() if k != 'errors'}), flush=True)

    try:
        with Session(engine) as session:
            groups, details, skipped = build_manifest(session)
        report = {'status': 'running', 'started_at': datetime.now(timezone.utc).isoformat(),
                  'unique_images': len(groups), 'total_images': sum(len(g['ids']) for g in groups),
                  'covers': sum(g['cover'] for g in groups), 'skipped_unavailable_references': skipped,
                  'processed': 0, 'ready_images': 0, 'ready_unique_images': 0, 'ready_covers': 0,
                  'failed': 0, 'errors': [], 'origins': {}, 'details_total': len(details),
                  'details_ready': 0, 'details_failed': 0}
        publish(report)
        service_token = settings.auth_service_token.get_secret_value()
        if service_token and urlsplit(base).hostname not in {'127.0.0.1', 'localhost', '::1'}:
            raise ValueError('internal cache credentials require a loopback API')
        with httpx.Client(timeout=90, headers={'X-Catalog-Service': service_token} if service_token else {}) as client:
            # Populate complete detail JSON before the slower original-image work.
            for endpoint in details:
                try:
                    response = client.get(base + endpoint)
                    response.raise_for_status()
                    report['details_ready'] += 1
                except httpx.TransportError:
                    raise
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code >= 500:
                        raise
                    report['details_failed'] += 1
                if (report['details_ready'] + report['details_failed']) % 250 == 0:
                    publish(report)
            publish(report)
            warm_images(groups, client, base, Path(settings.artifact_dir).parent / 'reference-images', cache, report, publish)
        report['status'] = 'partial' if report['failed'] or report['details_failed'] else 'complete'
        publish(report)
        return report
    except httpx.HTTPError:
        if 'report' in locals():
            report['status'] = 'retrying'
            publish(report)
        raise
    finally:
        engine.dispose()
        cache.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--watch', action='store_true', help='Keep warming new/expired images automatically')
    args = parser.parse_args()
    settings = Settings()
    base = 'http://127.0.0.1:' + os.getenv('API_PORT', '8092')
    while True:
        try:
            report = warm_once(settings, base)
        except (httpx.HTTPError, OSError):
            if not args.watch:
                raise
            print('Cache warmup temporarily unavailable; retrying in 30 seconds', flush=True)
            time.sleep(30)
            continue
        if not args.watch:
            return 0 if report['status'] == 'complete' else 1
        time.sleep(300 if report['status'] == 'partial' else 21600)


if __name__ == '__main__':
    raise SystemExit(main())
