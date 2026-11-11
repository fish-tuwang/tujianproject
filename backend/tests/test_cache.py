from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest
from redis.exceptions import ConnectionError
from sqlalchemy import event
from backend.app.cache import CatalogCache
from backend.app.repository import CatalogRepository
from backend.app.schemas import SourceCandidate, TomicaQuery
from backend.app.reference_images import LOCKS, cached_reference, reference_path


class MemoryRedis:
    def __init__(self):
        self.values = {}
        self.expirations = {}
    def get(self, key):
        return self.values.get(key)
    def set(self, key, value, ex):
        self.values[key] = value
        self.expirations[key] = ex
    def close(self):
        pass


def test_numbered_pages_are_disjoint_and_filter_counts_are_correct(session):
    repo = CatalogRepository(session)
    for index in range(45):
        repo.publish_candidates(None, [SourceCandidate(kind='tomica_model', source_key=str(index), fields={'number': str(index), 'name_original': 'car'+str(index), 'brand': 'Toyota' if index < 22 else 'Honda', 'release_year': 2020})])
    pages = [repo.list_tomica(TomicaQuery(page=p, limit=20)) for p in [1, 2, 3]]
    assert [len(p['items']) for p in pages] == [20, 20, 5]
    assert len({i['id'] for p in pages for i in p['items']}) == 45
    assert all(p['total'] == 45 and p['total_pages'] == 3 for p in pages)
    filtered = repo.list_tomica(TomicaQuery(page=2, limit=20, brand='Toyota'))
    assert len(filtered['items']) == 2 and filtered['total'] == 22
    assert repo.list_tomica(TomicaQuery(page=999, limit=20))['page'] == 3
    with pytest.raises(ValueError):
        TomicaQuery(page=1, cursor='cursor')


def test_snapshot_cache_avoids_repeat_table_scans_and_revision_invalidates(session):
    cache = CatalogCache(client=MemoryRedis())
    repo = CatalogRepository(session, cache)
    for index in range(25):
        repo.publish_candidates(None, [SourceCandidate(kind='tomica_model', source_key=str(index), fields={'number':str(index), 'name_original':'car', 'brand':'Honda'})])
    scans = []
    def record(connection, cursor, statement, parameters, context, many):
        if 'from tomica_models' in statement.lower():
            scans.append(statement)
    event.listen(session.get_bind(), 'before_cursor_execute', record)
    try:
        first = repo.list_tomica(TomicaQuery(page=1, limit=20))
        repo.list_tomica(TomicaQuery(page=2, limit=20))
        assert len(scans) == 1
        repo.set_override('tomica_model', first['items'][0]['id'], 'brand', 'Toyota')
        assert repo.list_tomica(TomicaQuery(page=1, limit=20, brand='Toyota'))['total'] == 1
        assert len(scans) >= 2
    finally:
        event.remove(session.get_bind(), 'before_cursor_execute', record)


def test_cache_failure_falls_back_and_cools_down():
    class Unavailable:
        calls = 0
        def get(self, key):
            self.calls += 1
            raise ConnectionError('offline')
    client = Unavailable()
    cache = CatalogCache(client=client)
    assert cache.remember('a', lambda: ['database']) == ['database']
    assert cache.remember('b', lambda: ['database']) == ['database']
    assert client.calls == 1


def test_decoded_snapshot_is_shared_and_replaced_on_revision_or_expiry():
    cache = CatalogCache(client=MemoryRedis())
    rows = [{'id': 'b'}, {'id': 'a'}]
    first = cache.snapshot('tomica', 1, lambda: rows)
    assert cache.snapshot('tomica', 1, lambda: pytest.fail('unnecessary reload')) is first
    fresh = cache.snapshot('tomica', 2, lambda: [{'id': 'c'}])
    assert fresh == [{'id': 'c'}] and fresh is not first
    assert len(cache.snapshots) == 1
    cache.snapshot('pokemon', 1, lambda: [{'dex': 1}])
    assert len(cache.snapshots) == 2
    revision, expiry, previous = cache.snapshots['tomica']
    cache.snapshots['tomica'] = (revision, 0, previous)
    assert cache.snapshot('tomica', 2, lambda: pytest.fail('Redis hit expected')) == fresh
    assert cache.snapshots['tomica'][2] is not previous


def test_pagination_does_not_mutate_the_shared_snapshot(session):
    rows = [{'id': 'b', 'release_year': 2025}, {'id': 'a', 'release_year': 2020}]
    repo = CatalogRepository(session)
    result = repo._page(rows, TomicaQuery(page=1, limit=20), 'tomica', lambda r: (r['release_year'], r['id']))
    assert [r['id'] for r in result['items']] == ['a', 'b']
    assert [r['id'] for r in rows] == ['b', 'a']


def test_disk_image_hit_needs_neither_dns_nor_source_lock(tmp_path):
    url = 'https://s1.52poke.com/wiki/original.png'
    data = b'RIFF1234WEBPoriginal'
    reference_path('id', url, tmp_path).write_bytes(data)
    lock = LOCKS['s1.52poke.com']
    def forbidden(_):
        raise AssertionError('DNS/source request on cache hit')
    pool = ThreadPoolExecutor(1)
    lock.acquire()
    try:
        future = pool.submit(cached_reference, 'id', url, tmp_path, validate=forbidden)
        path, mime = future.result(timeout=1)
        assert path.read_bytes() == data and mime == 'image/webp'
    finally:
        lock.release()
        pool.shutdown()
