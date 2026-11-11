from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from backend.app.config import Settings
from backend.app.models import SourcePage, SyncRun, SyncItem, TomicaModel, SourceIdentity
from backend.app.repository import CatalogError
from backend.app.sources.base import FetchResult
from backend.app.sync.service import SyncService
from backend.app.worker import enqueue_scheduled, triggers

class Lease:
    connection = None
    def assert_alive(self): pass
    def close(self): pass

class Locks:
    def acquire(self, source): return Lease()

class Client:
    def __init__(self, fail=False, unchanged=False):
        self.calls, self.fail, self.unchanged = [], fail, unchanged
    def fetch(self, url, *args):
        self.calls.append(url)
        if self.fail:
            return FetchResult(url, error='HTTP_429', retry_after=400)
        if url.endswith('menu.html'):
            if self.unchanged:
                return FetchResult(url, status=304, not_modified=True)
            return FetchResult(url, status=200, body=b'<a href="number/tba000.html">001</a>', content_hash='menu')
        return FetchResult(url, status=200, body=(Path(__file__).parent/'fixtures/tomica-number.html').read_bytes(), content_hash='detail')


def setup(session, client):
    factory = sessionmaker(session.get_bind(), expire_on_commit=False)
    service = SyncService(session, Settings(_env_file=None), session_factory=factory, http_client=client, lock_provider=Locks())
    return service, factory


def test_busy_and_weekly_followup(session):
    service, factory = setup(session, Client())
    run_id = service.enqueue_run('tomica', 'incremental')
    session.commit()
    with pytest.raises(CatalogError) as error:
        service.enqueue_run('tomica', 'full')
    assert error.value.status == 409
    session.rollback()
    enqueue_scheduled(factory, service.settings, 'tomica', 'full')
    session.expire_all()
    assert session.get(SyncRun, run_id).mode == 'full'
    session.get(SyncRun, run_id).status = 'running'
    session.commit()
    enqueue_scheduled(factory, service.settings, 'tomica', 'full')
    session.expire_all()
    assert session.get(SyncRun, run_id).followup_mode == 'full'


def test_limited_resume_and_cache_details(session):
    client = Client()
    service, factory = setup(session, client)
    run_id = service.enqueue_run('tomica', 'full', limit=1)
    session.commit()
    result = service.run_once(run_id)
    assert result.status == 'limited' and not result.complete
    session.expire_all()
    assert session.scalar(select(SyncItem).where(SyncItem.status == 'pending'))
    run = session.get(SyncRun, run_id)
    run.limit, run.status = 1, 'queued'
    session.commit()
    assert service.run_once(run_id).counts['changed'] > 0
    # 避免追踪样本中的外链导致测试扩大到整个网站：只对已知详情验证缓存。
    session.expire_all()
    page = session.scalar(select(SourcePage).where(SourcePage.url.like('%menu.html')))
    assert page.discovered_urls
    assert any('/number/' in u for u in client.calls)


def test_failure_preserves_old_data(session):
    session.add(TomicaModel(number='1', name_original='original'))
    session.commit()
    service, factory = setup(session, Client(fail=True))
    run_id = service.enqueue_run('tomica', 'full')
    session.commit()
    assert service.run_once(run_id).status == 'partial'
    session.expire_all()
    assert session.scalar(select(TomicaModel)).name_original == 'original'
    assert session.scalar(select(SyncItem)).next_retry_at is not None


def test_timezone_trigger():
    date = datetime(2026, 11, 9, 2, tzinfo=ZoneInfo('Asia/Shanghai'))
    assert triggers()['daily'].get_next_fire_time(None, date).hour == 3
    assert triggers()['weekly'].get_next_fire_time(None, date).weekday() == 6


def test_model_cover_follows_source_order_not_random_uuid(session):
    from backend.app.repository import CatalogRepository
    from backend.app.sources.tomica import TomicaAdapter
    from backend.app.models import ImageAsset
    service, _ = setup(session, Client())
    parsed = TomicaAdapter().parse('http://tomica.minibird.jp/t-tomica/number/tba000.html', (Path(__file__).parent/'fixtures/tomica-number.html').read_bytes())
    repo = CatalogRepository(session)
    service.attach_images(parsed, session)
    repo.publish_candidates(None, parsed.candidates)
    first = next(c for c in parsed.candidates if c.kind == 'tomica_variant' and c.evidence.get('model_key') == '001-1')
    service.link_model_images(session, parsed)
    identity = session.scalar(select(SourceIdentity).where(SourceIdentity.source_key == '001-1'))
    model = session.get(TomicaModel, identity.entity_id)
    assert model.primary_image_id == first.fields['image_id']
    assert '637.jpg' in session.get(ImageAsset, model.primary_image_id).source_url
    assert service.link_model_images(session, parsed) == 0


def test_uncoded_special_new_photos_reuse_existing_identity(session):
    from backend.app.repository import CatalogRepository
    from backend.app.schemas import SourceCandidate, TomicaQuery
    from backend.app.sync.identity import IdentityResolver
    repo=CatalogRepository(session)
    evidence={'url':'http://tomica.minibird.jp/t-tomica/number/tbas01.html','display_title':'special model','image_urls':['original.jpg']}
    old=SourceCandidate(kind='tomica_model',source_key='SP:original',fields={'number':'SP','name_original':'special model'},evidence=evidence)
    repo.publish_candidates(None,[old])
    old_id=repo.list_tomica(TomicaQuery())['items'][0]['id']
    updated=old.model_copy(deep=True);updated.source_key='SP:updated';updated.evidence['image_urls'].append('new.jpg')
    assert IdentityResolver().resolve(updated,repo).entity_key=='SP:updated'
    repo.publish_candidates(None,[updated])
    assert [r['id'] for r in repo.list_tomica(TomicaQuery())['items']]==[old_id]
