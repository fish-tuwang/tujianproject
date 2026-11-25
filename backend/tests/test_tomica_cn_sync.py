from datetime import datetime, timedelta
from io import BytesIO
import hashlib
import json
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import httpx
from PIL import Image
import pytest
from sqlalchemy import select

from backend.app import tomica_cn_sync as module
from backend.app.models import TomicaModel, TomicaNews
from backend.app.repository import CatalogRepository
from backend.tests.test_api import client

URL = 'https://www.tomy.cn/tomica/item/01diecastcar/car-a'
PHOTO = 'https://www.tomy.cn/wp-content/uploads/2024/03/car.png'


def html(name='Car A', price='35'):
    return f'''<meta property="article:published_time" content="2026-11-04T03:09:42+00:00">
    <meta property="article:modified_time" content="2026-11-04T03:09:42+00:00">
    <h2 class="l-product-detail">{name}</h2><div class="js-image"><img src="{PHOTO}"></div>
    <div class="js-thumbnails"><img src="{PHOTO}"></div>
    <ul class="table l-product-detail"><dl><dt>参考价格：</dt><dd>{price}</dd></dl></ul>'''


def make_job(session, tmp_path):
    app = SimpleNamespace(state=SimpleNamespace(settings=SimpleNamespace(
        artifact_dir=str(tmp_path), source_interval_seconds=0), session_factory=lambda: session))
    job = module.ChinaSync(app)
    job.directory.mkdir(parents=True)
    return job


def test_publication_month_comes_from_metadata_not_photo_upload_or_car_model_year():
    value = module.product_page(URL, html('Car 1984 reissue'))
    assert value['published_at'].startswith('2026-11-04T11:09:42')
    assert value['images'] == [PHOTO]
    assert value['properties'] == {'参考价格': '35'}
    assert 'release_year' not in value


@pytest.mark.parametrize('url', ['https://evil.example/tomica/item/c/a',
    'http://www.tomy.cn/tomica/item/c/a', 'https://www.tomy.cn/wp-admin/',
    'https://www.tomy.cn/tomica/item/c/a?redirect=evil', 'https://www.tomy.cn/tomica/item/c/a/extra'])
def test_fixed_china_source_boundary(url):
    with pytest.raises(ValueError):
        module.source_url(URL, url)


def test_only_real_archive_pagination_and_product_cards_are_followed():
    body = f'''<a href="{URL}"><h3>Car A</h3><img src="{PHOTO}"></a>
    <div class="pagination"><a href="/tomica_item/01diecastcar/page/2">Next</a></div>
    <a href="https://evil.example/tomica/item/c/b"><h3>wrong</h3></a>'''
    pages, records = module.listing_page(module.ROOTS[0], body)
    assert pages == {'https://www.tomy.cn/tomica_item/01diecastcar/page/2'}
    assert records == {URL: {'name': 'Car A', 'cover': PHOTO}}


def test_schedule_keeps_48_hour_phase_across_restart_and_month_boundary():
    now = datetime(2026, 11, 25, 20, tzinfo=ZoneInfo('Asia/Shanghai'))
    first = module.trigger().get_next_fire_time(None, now)
    second = module.trigger().get_next_fire_time(first, first)
    assert first.hour == 3 and second - first == timedelta(days=2)
    assert module.trigger().get_next_fire_time(None, now + timedelta(hours=1)) == first


def test_incremental_comparison_does_not_call_existing_products_new(session, tmp_path, monkeypatch):
    job = make_job(session, tmp_path)
    old = module.product_page(URL, html())
    old['listing'] = {'name': 'Car A', 'cover': PHOTO}
    other = URL.replace('car-a', 'car-b')
    archive = f'<a href="{URL}"><h3>Car A</h3><img src="{PHOTO}"></a><a href="{other}"><h3>Car B</h3><img src="{PHOTO}"></a>'
    monkeypatch.setattr(module, 'ROOTS', ['https://www.tomy.cn/tomica_item/item'])
    documents = {module.ROOTS[0]: archive, 'https://www.tomy.cn/tomica': archive,
                 URL: html(), other: html('Car B')}
    monkeypatch.setattr(job, 'get', lambda client, url: documents[url])
    records, active, new, changed = job.crawl(None, {URL: old})
    assert new == [other] and changed == [] and len(active) == 2
    records2, _, new2, changed2 = job.crawl(None, records)
    assert not new2 and not changed2 and records2 == records
    documents[URL] = html(price='39')
    _, _, new3, changed3 = job.crawl(None, records)
    assert not new3 and changed3 == [URL]


def test_monthly_news_is_cached_idempotent_and_does_not_modify_catalogue(session, tmp_path):
    job = make_job(session, tmp_path)
    car = TomicaModel(number='63', name_original='existing car', release_year=1970)
    session.add(car)
    session.add(TomicaNews(slug='user-upload', archive_month='2026-11', title='Original',
        source_name='User', source_url='https://example.com/', content_hash='old', data={'products': []}))
    session.commit()
    car_id = car.id
    record = module.product_page(URL, html())
    body = BytesIO()
    Image.new('RGB', (30, 20), 'blue').save(body, 'PNG')
    calls = []
    def response(request):
        calls.append(request.url)
        return httpx.Response(200, content=body.getvalue(), headers={'Content-Type': 'image/png'})
    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        assert job.publish_news(client, {URL: record}, {URL: {}}, set()) == 1
        first_revision = CatalogRepository(session).get_revision('tomica-news')
        assert job.publish_news(client, {URL: record}, {URL: {}}, set()) == 0
        assert len(calls) == 1 and CatalogRepository(session).get_revision('tomica-news') == first_revision
    rows = list(session.scalars(select(TomicaNews)))
    assert len(rows) == 2 and session.get(TomicaModel, car_id).release_year == 1970
    row = next(r for r in rows if r.slug.startswith('cn-'))
    digest = row.data['products'][0]['cover_digest']
    assert row.archive_month == '2026-11' and row.data['origin'] == 'official-cn'
    assert (job.directory / 'images' / (digest + '.jpg')).read_bytes() == body.getvalue()
    assert next(r for r in rows if r.slug == 'user-upload').content_hash == 'old'


def test_manual_trigger_is_fixed_source_and_rejects_cross_site_or_arbitrary_targets(client, monkeypatch):
    calls = []
    job = client.app.state.tomica_cn_sync
    monkeypatch.setattr(job, 'submit', lambda reason: calls.append(reason) or {'status': 'queued', 'run_id': 'test'})
    headers = {'x-catalog-client': 'web'}
    assert client.post('/api/tomica-maintenance/china/run', json={}, headers=headers).status_code == 202
    assert calls == ['manual']
    assert client.post('/api/tomica-maintenance/china/run', json={'url': 'https://evil.example'}, headers=headers).status_code == 422
    assert client.post('/api/tomica-maintenance/china/run', json={}, headers={**headers, 'sec-fetch-site': 'cross-site'}).status_code == 403
    assert calls == ['manual']


def test_china_news_photos_are_served_from_writable_cache(client, tmp_path):
    client.app.state.settings.artifact_dir = str(tmp_path)
    body = BytesIO()
    Image.new('RGB', (20, 20), 'green').save(body, 'PNG')
    digest = hashlib.sha256(body.getvalue()).hexdigest()
    directory = module.storage(client.app.state.settings) / 'images'
    directory.mkdir(parents=True)
    (directory / (digest + '.jpg')).write_bytes(body.getvalue())
    result = client.get('/api/tomica-news/images/' + digest)
    assert result.status_code == 200 and result.content == body.getvalue()
    assert result.headers['content-type'].startswith('image/png')


def test_captured_baseline_is_complete_and_has_real_publication_metadata():
    data = json.loads(module.BASELINE.read_text(encoding='utf-8'))['products']
    assert len(data) == 558
    assert sum(r.get('published_at', '').startswith('2026-11') for r in data.values()) == 17
    for url, row in data.items():
        assert module.source_url(url, url) == url and row['source_url'] == url
        assert row['listing'] and row['images']


def test_duplicate_manual_requests_join_the_existing_run(session, tmp_path):
    job = make_job(session, tmp_path)
    first = job.submit()
    second = job.submit()
    assert first['status'] == 'queued' and second['status'] == 'already_running'
    assert second['run_id'] == first['run_id']


def test_failed_source_does_not_advance_the_saved_inventory(session, tmp_path, monkeypatch):
    import sys
    job = make_job(session, tmp_path)
    monkeypatch.setitem(sys.modules, 'fcntl', SimpleNamespace(LOCK_EX=1, LOCK_NB=2, flock=lambda *args: None))
    def failed(*args):
        raise httpx.ReadTimeout('source timeout')
    monkeypatch.setattr(job, 'crawl', failed)
    job.run_once('test-run', 'manual')
    assert job.snapshot()['status'] == 'failed'
    assert not (job.directory / 'inventory.json').exists()
