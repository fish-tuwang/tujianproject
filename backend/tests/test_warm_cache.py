import os
import time

import httpx
import pytest

from backend.app.cache import CatalogCache
from backend.app.models import ImageAsset, Pokemon, TomicaModel
from backend.app.reference_images import REFERENCE_CACHE_SECONDS, read_reference, reference_path
from scripts.warm_cache import build_manifest, warm_group
from backend.tests.test_cache import MemoryRedis


def test_warmer_deduplicates_registered_urls_and_prioritizes_covers(session):
    url = 'http://tomica.minibird.jp/t-tomica/a.jpg'
    assets = [ImageAsset(source_url=url), ImageAsset(source_url=url.replace("a.jpg", "%61.jpg")),
              ImageAsset(source_url='https://s1.52poke.com/wiki/p.png'),
              ImageAsset(source_url='http://tomica.minibird.jp/t-tomica/b.jpg'),
              ImageAsset(source_url='https://unregistered.invalid/a.jpg')]
    session.add_all(assets)
    session.flush()
    session.add(TomicaModel(number='1', name_original='car', release_year=1970, primary_image_id=assets[1].id))
    session.add(Pokemon(dex=1, name_zh='test', primary_image_id=assets[2].id))
    session.flush()
    groups, details, skipped = build_manifest(session)
    assert len(groups) == 3 and skipped == 1
    assert groups[0]['url'] == url and groups[0]['cover']
    assert set(groups[0]['ids']) == {assets[0].id, assets[1].id}
    assert groups[1]['cover'] and not groups[2]['cover']
    assert len(details) == 2 and details[1] == '/api/pokemon/1'


def test_gunpla_cover_precedes_its_detail_and_includes_protected_detail_endpoint(session):
    from backend.app.models import GunplaEntry
    assets = [ImageAsset(source_url='https://staticcdn.bandaihobbysite.cn/www/uploads/cover.jpg'), ImageAsset(source_url='https://staticcdn.bandaihobbysite.cn/www/uploads/detail.jpg')]
    session.add_all(assets); session.flush()
    session.add(GunplaEntry(kind='product', source_key='3425', name='fixture', content_hash='fixture', data={'cover_image_id': assets[0].id, 'gallery_image_ids': [assets[1].id], 'release_sort': '2026-08-01'}))
    session.flush()
    groups, details, skipped = build_manifest(session)
    assert groups[0]['cover'] and groups[0]['ids'] == [assets[0].id]
    assert not groups[1]['cover'] and skipped == 0
    assert details == ['/api/gunpla/products/3425']


def test_warmer_fetches_once_and_resumes_from_exact_original_bytes(tmp_path):
    data = b'GIF89a' + b'original pixels'
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(200, content=data, headers={'content-type': 'image/gif'})
    group = {'ids': ['id-a', 'id-b'], 'url': 'http://tomica.minibird.jp/t-tomica/a.gif'}
    cache = CatalogCache(client=MemoryRedis())
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        warm_group(group, client, 'http://127.0.0.1:8092', tmp_path, cache)
        warm_group(group, client, 'http://127.0.0.1:8092', tmp_path, cache)
    assert len(requests) == 1
    for asset_id in group['ids']:
        assert read_reference(asset_id, group['url'], tmp_path) == data
        assert cache.get('image:' + asset_id) == data


def test_warmer_does_not_cache_html(tmp_path):
    group = {'ids': ['id-a'], 'url': 'http://tomica.minibird.jp/t-tomica/a.gif'}
    cache = CatalogCache(client=MemoryRedis())
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b'<html>denied</html>', headers={'content-type': 'image/png'}))) as client:
        with pytest.raises(ValueError):
            warm_group(group, client, 'http://127.0.0.1:8092', tmp_path, cache)
    assert not list(tmp_path.iterdir()) and cache.get('image:id-a') is None


def test_disk_originals_survive_a_day_and_refresh_after_thirty(tmp_path):
    url = 'http://tomica.minibird.jp/t-tomica/a.gif'
    path = reference_path('id-a', url, tmp_path)
    path.write_bytes(b'GIF89aoriginal')
    two_days_ago = time.time() - 2 * 86400
    os.utime(path, (two_days_ago, two_days_ago))
    assert read_reference('id-a', url, tmp_path) == b'GIF89aoriginal'
    expired = time.time() - REFERENCE_CACHE_SECONDS - 1
    os.utime(path, (expired, expired))
    assert read_reference('id-a', url, tmp_path) is None

def test_api_outage_stops_queue_without_marking_every_original_failed(tmp_path):
    from scripts.warm_cache import warm_images
    requests = []
    def offline(request):
        requests.append(request)
        raise httpx.ConnectError('API restarting', request=request)
    groups = [{'ids': [str(index)], 'url': f'http://tomica.minibird.jp/t-tomica/{index}.gif', 'cover': True} for index in range(50)]
    report = {'processed': 0, 'failed': 0, 'errors': []}
    with httpx.Client(transport=httpx.MockTransport(offline)) as client:
        with pytest.raises(httpx.ConnectError):
            warm_images(groups, client, 'http://127.0.0.1:8092', tmp_path, CatalogCache(client=MemoryRedis()), report, lambda _: None)
    assert len(requests) == 1 and report['failed'] == 0
