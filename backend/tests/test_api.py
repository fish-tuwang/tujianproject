import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from backend.app.api import get_session
from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.repository import CatalogRepository
from backend.app.schemas import SourceCandidate


@pytest.fixture
def client(session):
    app = create_app(Settings(_env_file=None, database_url='sqlite://', admin_token='test-admin'))
    factory = sessionmaker(session.get_bind(), expire_on_commit=False)
    def dependency():
        with factory() as value:
            yield value
    app.dependency_overrides[get_session] = dependency
    app.state.session_factory = factory
    with TestClient(app) as value:
        yield value


def seed(session):
    repo = CatalogRepository(session)
    repo.publish_candidates(None, [SourceCandidate(kind='tomica_model',source_key='a',fields={'number':'001','name_original':'Nissan','brand':'Nissan','release_year':2024}), SourceCandidate(kind='tomica_model',source_key='b',fields={'number':'001','name_original':'unknown'})])
    for dex in [10,2]:repo.publish_candidates(None,[SourceCandidate(kind='pokemon',source_key=str(dex),fields={'dex':dex,'name_zh':str(dex),'types':['草']})])
    session.commit()


def test_queries_errors_and_health(client, session):
    seed(session)
    assert client.get('/api/tomica/filters').json()['brands']==['Nissan']
    assert len(client.get('/api/tomica?brand=Nissan&year=2024').json()['items'])==1
    assert len(client.get('/api/tomica?year=unknown').json()['items'])==1
    assert [r['dex'] for r in client.get('/api/pokemon?type=草').json()['items']]==[2,10]
    assert client.get('/api/pokemon/9999').status_code==404
    assert client.get('/api/tomica?limit=0').status_code==422
    assert client.get('/api/pokemon?type=nope').status_code==422
    assert client.get('/health/live').status_code==200
    assert client.get('/health/ready').status_code==503


def test_admin_queue_only_and_busy(client):
    assert client.post('/api/admin/sync',json={'source':'tomica','mode':'full'}).status_code==401
    headers={'Authorization':'Bearer test-admin'}
    response=client.post('/api/admin/sync',json={'source':'tomica','mode':'full'},headers=headers)
    assert response.status_code==202
    assert client.post('/api/admin/sync',json={'source':'tomica','mode':'full'},headers=headers).status_code==409
    assert client.get('/api/admin/runs',headers=headers).json()['items'][0]['status']=='queued'
    assert 'test-admin' not in client.get('/admin/').text


def test_overrides_effective_and_revision(client,session):
    seed(session)
    page=client.get('/api/tomica?limit=1').json()
    entity=page['items'][0]['id']; headers={'Authorization':'Bearer test-admin'}
    response=client.patch('/api/admin/overrides',json={'kind':'tomica_model','entity_key':entity,'field':'brand','value':'Toyota'},headers=headers)
    assert response.status_code==200 and response.json()['source_value']=='Nissan'
    assert client.get('/api/tomica?brand=Toyota').json()['items'][0]['id']==entity
    assert client.get('/api/tomica',params={'cursor':page['next_cursor']}).status_code==409
    assert client.patch('/api/admin/overrides',json={'kind':'tomica_model','entity_key':entity,'field':'id','value':'bad'},headers=headers).status_code==422


def test_admin_disabled():
    app=create_app(Settings(_env_file=None,database_url='sqlite://',admin_token=''))
    with TestClient(app) as client:
        assert client.get('/api/admin/runs').status_code==503


def test_reference_endpoint_never_accepts_arbitrary_urls(client):
    assert client.get('/api/reference-images/not-a-uuid').status_code == 422
    assert client.get('/api/reference-images/00000000-0000-0000-0000-000000000001').status_code == 404


def test_public_query_cache_and_override_invalidation(client, session):
    from backend.app.cache import CatalogCache
    from backend.tests.test_cache import MemoryRedis
    client.app.state.cache = CatalogCache(client=MemoryRedis())
    seed(session)
    first = client.get('/api/tomica?page=1&limit=20')
    second = client.get('/api/tomica?page=1&limit=20')
    assert first.status_code == second.status_code == 200
    assert first.headers['x-catalog-cache'] == 'miss' and second.headers['x-catalog-cache'] == 'hit'
    assert first.json() == second.json() and second.json()['total'] == 2
    entity = first.json()['items'][0]['id']
    client.patch('/api/admin/overrides', json={'kind':'tomica_model','entity_key':entity,'field':'brand','value':'Toyota'}, headers={'Authorization':'Bearer test-admin'})
    changed = client.get('/api/tomica?brand=Toyota&page=1&limit=20')
    assert changed.json()['total'] == 1


def test_redis_image_bytes_and_conditional_response(client, session):
    from backend.app.cache import CatalogCache
    from backend.app.models import ImageAsset
    from backend.tests.test_cache import MemoryRedis
    memory = MemoryRedis()
    client.app.state.cache = CatalogCache(client=memory)
    image = ImageAsset(source_url='https://s1.52poke.com/wiki/original.png')
    session.add(image); session.commit()
    data = b'RIFF1234WEBPoriginal'
    client.app.state.cache.set('image:'+image.id, data, ttl=86400)
    response = client.get('/api/reference-images/'+image.id)
    assert response.content == data and response.headers['x-catalog-cache'] == 'redis'
    assert response.headers['content-type'] == 'image/webp'
    assert client.get('/api/reference-images/'+image.id, headers={'If-None-Match':response.headers['etag']}).status_code == 304


def test_cold_image_download_releases_database_session_first(client, monkeypatch, tmp_path):
    from types import SimpleNamespace
    from uuid import uuid4
    from backend.app import reference_images
    identity = str(uuid4())
    class MetadataSession:
        released = False
        def get(self, model, key):
            return SimpleNamespace(id=identity, source_url='https://s1.52poke.com/wiki/picture.png', public_url=None, status='pending', attribution=None)
        def close(self):
            self.released = True
    metadata = MetadataSession()
    def dependency():
        yield metadata
    client.app.dependency_overrides[get_session] = dependency
    monkeypatch.setattr(reference_images, 'read_reference', lambda *a: None)
    def download(*args):
        assert metadata.released, 'cold source request must not retain the database connection'
        path = tmp_path / 'image'
        path.write_bytes(b'RIFF1234WEBPimage')
        return path, 'image/webp'
    monkeypatch.setattr(reference_images, 'cached_reference', download)
    response = client.get('/api/reference-images/'+identity)
    assert response.status_code == 200 and response.headers['x-catalog-cache'] == 'source'
