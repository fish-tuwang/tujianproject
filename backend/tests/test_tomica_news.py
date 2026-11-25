from copy import deepcopy
import hashlib
import json
import socket

import pytest
from redis.exceptions import ConnectionError
from sqlalchemy import func, select

from backend.app.cache import CatalogCache
from backend.app.config import ROOT
from backend.app.models import CatalogRevision, TomicaNews
from backend.app.news import NEWS_IMAGES, news_index, read_news_image
from backend.app.repository import CatalogRepository
from backend.tests.test_api import client
from backend.tests.test_cache import MemoryRedis
from scripts.seed_tomica_news import import_articles, load_articles

TRUCK = {
 'c84f407b7f2e90bd2e40258405bb69601672e1f65907b0fd5679ca74cb30e580',
 '9c18b06f8f4b4746b14262a271c97e2e0b51db77237c211a9629bff49898e9ad',
 '30ca56536fca0ba1d94dc7c3185b7ac4f8d25f911d47ec366b3e4676dbfd37c1',
 'e26100cb59f68a9d1cd3502f034ef4257866c398a3d0abec63bb8bb3cec28618',
 'd9de38651b19c3f8405868063c874c71f6539b32e439e14d4fc84982f93a6f7e'}
RESCUE = '4cc8103019e80de9d7f8b327d1b5b00fe0e26564b52e7b4582465c288b1bc855'
SUV = '14dabddb217529c251fe71415b57ed2098199bc0580895b3e93d99e91ee36680'


@pytest.fixture
def articles():
    return load_articles(ROOT / 'backend/data/tomica-news')


def publish(session, articles):
    stats = import_articles(session, articles)
    session.commit()
    return stats


def test_import_is_idempotent_and_changes_only_news_revision(session, articles):
    session.add_all([CatalogRevision(source='tomica', revision=8), CatalogRevision(source='pokemon', revision=9)])
    assert publish(session, articles) == {'created': 1, 'updated': 0, 'unchanged': 0}
    row = session.scalar(select(TomicaNews))
    times = (row.checked_at, row.updated_at)
    assert publish(session, articles) == {'created': 0, 'updated': 0, 'unchanged': 1}
    session.refresh(row)
    assert times == (row.checked_at, row.updated_at)
    repo = CatalogRepository(session)
    assert repo.get_revision('tomica-news') == 1
    changed = deepcopy(articles)
    changed[0]['data']['products'][0]['summary'] += ' 新的观察说明。'
    assert publish(session, changed)['updated'] == 1
    assert repo.get_revision('tomica-news') == 2
    assert (repo.get_revision('tomica'), repo.get_revision('pokemon')) == (8, 9)
    assert session.scalar(select(func.count()).select_from(TomicaNews)) == 1


def test_original_photos_match_the_seven_supplied_groups(articles):
    products = articles[0]['data']['products']
    assert products[0]['name'] == 'No.114 植木屋さんトラック'
    assert {p['digest'] for p in products[0]['photos']} == TRUCK
    assert [p['digest'] for p in products[1]['photos']] == [RESCUE]
    assert [p['digest'] for p in products[2]['photos']] == [SUV]
    for digest in TRUCK | {RESCUE, SUV}:
        data, mime = read_news_image(digest)
        assert hashlib.sha256(data).hexdigest() == digest and mime == 'image/jpeg'


@pytest.mark.parametrize('invalid', ['month', 'id', 'overlap', 'cover', 'url', 'empty', 'missing'])
def test_invalid_import_is_rejected_before_database_writes(tmp_path, session, articles, invalid):
    article = deepcopy(articles[0])
    products = article['data']['products']
    if invalid == 'month':
        article['archive_month'] = '2026-13'
    elif invalid == 'id':
        products[1]['id'] = products[0]['id']
    elif invalid == 'overlap':
        products[1]['photos'] = deepcopy(products[0]['photos'])
        products[1]['cover_digest'] = products[0]['cover_digest']
    elif invalid == 'cover':
        products[0]['cover_digest'] = SUV
    elif invalid == 'url':
        article['source_url'] = 'javascript:alert(1)'
    elif invalid == 'empty':
        article['data']['products'] = []
    else:
        products[0]['photos'][0]['digest'] = products[0]['cover_digest'] = '0' * 64
    (tmp_path / 'a.json').write_text(json.dumps(article), encoding='utf-8')
    with pytest.raises(ValueError):
        load_articles(tmp_path)
    assert session.scalar(select(func.count()).select_from(TomicaNews)) == 0


def test_original_digest_mismatch_is_rejected(tmp_path):
    (tmp_path / (SUV + '.jpg')).write_bytes(b'\xff\xd8\xffwrong original')
    with pytest.raises(ValueError, match='digest'):
        read_news_image(SUV, tmp_path)


def test_month_index_is_descending_and_thin(session, articles):
    older = deepcopy(articles[0])
    older.update(slug='2026-10-tomica', archive_month='2026-10')
    publish(session, articles + [older])
    index = news_index(session)['items']
    assert [m['month'] for m in index] == ['2026-11', '2026-10']
    assert [m['product_count'] for m in index] == [3, 3]
    assert 'photos' not in index[0]['products'][0] and 'observations' not in index[0]['products'][0]


def test_month_api_and_revision_cache(client, session, articles):
    client.app.state.cache = CatalogCache(client=MemoryRedis())
    publish(session, articles)
    first = client.get('/api/tomica-news')
    assert first.json()['items'][0]['month'] == '2026-11'
    assert first.headers['x-catalog-cache'] == 'miss'
    assert client.get('/api/tomica-news').headers['x-catalog-cache'] == 'hit'
    detail = client.get('/api/tomica-news/2026-11')
    assert [len(p['photos']) for p in detail.json()['articles'][0]['products']] == [5, 1, 1]
    assert client.get('/api/tomica-news/2026-11').headers['x-catalog-cache'] == 'hit'
    assert client.get('/api/tomica-news/2026-10').status_code == 404
    for month in ['2026-13', '2026-1', 'wrong']:
        assert client.get('/api/tomica-news/' + month).status_code == 422
    changed = deepcopy(articles)
    changed[0]['data']['products'][0]['summary'] = '更新后的观察'
    publish(session, changed)
    updated = client.get('/api/tomica-news/2026-11')
    assert updated.headers['x-catalog-cache'] == 'miss'
    assert updated.json()['articles'][0]['products'][0]['summary'] == '更新后的观察'


def test_multiple_articles_in_one_month_share_one_index(client, session, articles):
    followup = deepcopy(articles[0])
    followup.update(slug='2026-11-followup', title='十一月新品补充消息')
    for product in followup['data']['products']:
        product['id'] = 'followup-' + product['id']
    older = deepcopy(articles[0])
    older.update(slug='2026-10-monthly', archive_month='2026-10', title='十月新品情报')
    publish(session, articles + [followup, older])
    index = client.get('/api/tomica-news').json()['items']
    assert [row['month'] for row in index] == ['2026-11', '2026-10']
    assert [row['product_count'] for row in index] == [6, 3]
    month = client.get('/api/tomica-news/2026-11').json()
    assert len(month['articles']) == 2
    assert {row['slug'] for row in month['articles']} == {'2026-11-tomica', '2026-11-followup'}
    assert len(client.get('/api/tomica-news/2026-10').json()['articles']) == 1


def test_original_image_cache_keeps_bytes_and_needs_no_network(client, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('news images must not access the source network')
    monkeypatch.setattr(socket, 'getaddrinfo', forbidden)
    client.app.state.cache = CatalogCache(client=MemoryRedis())
    for digest in TRUCK | {RESCUE, SUV}:
        response = client.get('/api/tomica-news/images/' + digest)
        assert response.status_code == 200 and response.headers['x-catalog-cache'] == 'disk'
        assert response.content == (NEWS_IMAGES / (digest + '.jpg')).read_bytes()
        assert hashlib.sha256(response.content).hexdigest() == digest
        hot = client.get('/api/tomica-news/images/' + digest)
        assert hot.content == response.content and hot.headers['x-catalog-cache'] == 'redis'
        etag = response.headers['etag']
        conditional = client.get('/api/tomica-news/images/' + digest, headers={'If-None-Match': etag})
        assert conditional.status_code == 304 and conditional.content == b''
    assert client.get('/api/tomica-news/images/' + '0' * 64).status_code == 404
    assert client.get('/api/tomica-news/images/invalid').status_code == 422
    assert client.get('/api/tomica-news/images/%2e%2e%2fconfig.py').status_code in {404, 422}


def test_original_local_file_survives_redis_outage(client):
    class Offline:
        def get(self, _):
            raise ConnectionError('offline')
        def close(self):
            pass
    client.app.state.cache = CatalogCache(client=Offline())
    response = client.get('/api/tomica-news/images/' + SUV)
    assert response.status_code == 200 and response.headers['x-catalog-cache'] == 'disk'
    assert hashlib.sha256(response.content).hexdigest() == SUV
