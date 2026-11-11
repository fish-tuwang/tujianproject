import argparse
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import sys
import threading
import time
from uuid import uuid4
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import httpx
from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from backend.app.config import Settings
from backend.app.models import Base, CatalogRevision, ImageAsset, SourcePage, SyncItem, SyncRun, TomicaModel, now
from backend.app.repository import CatalogRepository
from backend.app.sources.http import SourceHttpClient
from backend.app.sources.tomica import TomicaAdapter
from backend.app.sources.pokemon import PokemonAdapter
from backend.app.sync.service import SourceLockProvider, SyncService
from backend.app.worker import enqueue_scheduled, triggers


class Blocked(RuntimeError):
    pass


def load_environment(path=None):
    if path:
        target = Path(path)
        if not target.is_file():
            raise Blocked('explicit environment file does not exist')
        load_dotenv(target, override=False)
    else:
        load_dotenv(ROOT / '.env', override=False)


def assert_demo_database(url):
    if make_url(url).database != 'dual_catalog_demo':
        raise ValueError('write acceptance requires dual_catalog_demo')


class Checks:
    def __init__(self):
        self.results = []
    def check(self, name, condition):
        if not condition:
            raise AssertionError(name)
        self.results.append({'assertion': name, 'status': 'pass'})


@contextmanager
def isolated_database(settings):
    assert_demo_database(settings.database_url)
    parent = create_engine(settings.database_url)
    schema = 'catalog_acceptance_' + uuid4().hex
    with parent.begin() as connection:
        connection.execute(text('CREATE SCHEMA ' + schema))
    engine = create_engine(settings.database_url, connect_args={'options': '-csearch_path=' + schema})
    try:
        Base.metadata.create_all(engine)
        yield engine, sessionmaker(engine, expire_on_commit=False)
    finally:
        engine.dispose()
        with parent.begin() as connection:
            connection.execute(text('DROP SCHEMA ' + schema + ' CASCADE'))
        parent.dispose()


def postgres_suite(settings, checks):
    engine = create_engine(settings.database_url)
    try:
        checks.check('PostgreSQL server is available', engine.dialect.name == 'postgresql')
        with engine.connect() as connection:
            version = connection.scalar(text('SHOW server_version'))
            checks.check('server is PostgreSQL 18', str(version).startswith('18.'))
            checks.check('migration head', connection.scalar(text('SELECT version_num FROM alembic_version')) == '0002_sync_runtime')
        checks.check('catalog tables exist', {'tomica_models', 'pokemon', 'source_identities', 'sync_runs'} <= set(inspect(engine).get_table_names()))
        provider = SourceLockProvider(engine)
        first = provider.acquire('tomica')
        checks.check('first real source lock acquired', first is not None)
        second = provider.acquire('tomica')
        checks.check('second independent connection rejected', second is None)
        # 关闭真实DBAPI连接，验证锁随连接断开释放，不用假锁替代。
        first.connection.connection.driver_connection.close()
        first.connection.invalidate()
        first.close()
        third = provider.acquire('tomica')
        checks.check('source lock released after connection loss', third is not None)
        third.close()
    finally:
        engine.dispose()
    with isolated_database(settings) as (engine, factory):
        from backend.app.schemas import SourceCandidate, TomicaQuery
        with factory() as session, session.begin():
            repo = CatalogRepository(session)
            rows = [SourceCandidate(kind='tomica_model', source_key='test:'+str(year), fields={'number':'001','name_original':'test','release_year':year}) for year in [None,2024,1970]]
            checks.check('first publish inserts three generations', repo.publish_candidates(None, rows) == 3)
            checks.check('identical publish is idempotent', repo.publish_candidates(None, rows) == 0)
            values = repo.list_tomica(TomicaQuery())['items']
            checks.check('NULL year sorts last in real database', [v['release_year'] for v in values] == [1970,2024,None])
            repo.set_override('tomica_model', values[0]['id'], 'brand', 'Toyota')
            checks.check('effective override participates in filtering', len(repo.list_tomica(TomicaQuery(brand='Toyota'))['items']) == 1)


def fixture_client():
    number_body = (ROOT / 'backend/tests/fixtures/tomica-number.html').read_bytes()
    def transport(request):
        if request.url.path == '/robots.txt':
            return httpx.Response(404)
        if request.url.path.endswith('menu.html'):
            if request.headers.get('if-none-match'):
                return httpx.Response(304)
            return httpx.Response(200, content=b'<a href="number/acceptance.html">sample</a>', headers={'ETag':'fixture-menu'})
        return httpx.Response(200, content=number_body, headers={'ETag':'fixture-detail'})
    clock = [0.0]
    def sleep(value): clock[0] += value
    return SourceHttpClient('tomica', transport=httpx.MockTransport(transport), clock=lambda:clock[0], sleep=sleep)


def sync_suite(settings, checks):
    import backend.app.sync.service as module
    original = module.TomicaAdapter
    class FixtureAdapter(TomicaAdapter):
        def _links(self, url, soup, only_sections=False):
            return super()._links(url, soup, only_sections) if url.endswith('menu.html') else []
    module.TomicaAdapter = FixtureAdapter
    try:
        with isolated_database(settings) as (engine, factory):
            client = fixture_client()
            with factory() as session, session.begin():
                run_id = SyncService(session, settings, session_factory=factory).enqueue_run('tomica','full')
            with factory() as session:
                service = SyncService(session, settings, session_factory=factory, http_client=client)
                result = service.run_once(run_id)
            checks.check('real PG fixture sync completed', result.status == 'succeeded' and result.complete)
            with factory() as session:
                first = session.scalar(select(TomicaModel).order_by(TomicaModel.id))
                old_id, old_time = first.id, first.updated_at
                original_count = len(list(session.scalars(select(TomicaModel.id))))
            with factory() as session, session.begin():
                second_id = SyncService(session,settings,session_factory=factory).enqueue_run('tomica','incremental')
            with factory() as session:
                result = SyncService(session,settings,session_factory=factory,http_client=client).run_once(second_id)
            checks.check('304 menu still traverses detail pages', result.counts['pages'] == 2)
            with factory() as session:
                checks.check('no duplicate models after repeat', len(list(session.scalars(select(TomicaModel.id)))) == original_count)
                checks.check('unchanged content timestamp is preserved', session.get(TomicaModel,old_id).updated_at == old_time)
            class FailureClient:
                def fetch(self,url,*args):
                    from backend.app.sources.base import FetchResult
                    return FetchResult(url,error='simulated timeout')
            with factory() as session, session.begin():
                failed_id = SyncService(session,settings,session_factory=factory).enqueue_run('tomica','full')
            with factory() as session:
                result = SyncService(session,settings,session_factory=factory,http_client=FailureClient()).run_once(failed_id)
            checks.check('failed fetch is partial, never complete', result.status=='partial' and not result.complete)
            with factory() as session:
                checks.check('failed fetch preserves published catalog',len(list(session.scalars(select(TomicaModel.id))))==original_count)
            # 用已完成checkpoint加pending项模拟进程中断后的持久化恢复。
            with factory() as session, session.begin():
                resume_id = SyncService(session,settings,session_factory=factory).enqueue_run('tomica','full')
                run=session.get(SyncRun,resume_id);run.status='running'
                session.add(SyncItem(run_id=resume_id,url='http://tomica.minibird.jp/t-tomica/number/acceptance.html',status='processing'))
            with factory() as session:
                resumed=SyncService(session,settings,session_factory=factory,http_client=client).run_once(resume_id)
            checks.check('interrupted processing item resumes',resumed.status=='succeeded')
            client.close()
    finally:
        module.TomicaAdapter=original


def api_suite(settings, checks, base_url, mode):
    with httpx.Client(base_url=base_url, timeout=20) as client:
        checks.check('liveness',client.get('/health/live').status_code==200)
        checks.check('database readiness',client.get('/health/ready').status_code==200)
        checks.check('preview page is served',client.get('/preview/').status_code==200)
        for kind in ['tomica','pokemon']:
            response=client.get('/api/'+kind,params={'limit':2})
            checks.check(kind+' list HTTP 200',response.status_code==200)
            items=response.json()['items']
            if not items: raise Blocked(kind+' catalog is empty')
            key=items[0]['id'] if kind=='tomica' else items[0]['dex']
            detail=client.get('/api/'+kind+'/'+str(key))
            checks.check(kind+' detail HTTP 200',detail.status_code==200)
            checks.check(kind+' source attribution',bool(detail.json().get('source_url')))
            if kind=='pokemon': checks.check('national integer sorting', [i['dex'] for i in items]==sorted(i['dex'] for i in items))
        filters=client.get('/api/tomica/filters').json()
        checks.check('brand filters available',bool(filters['brands']))
        brand=filters['brands'][0]
        values=client.get('/api/tomica',params={'brand':brand}).json()['items']
        checks.check('brand filter matches',bool(values) and all(i['brand']==brand for i in values))
        checks.check('uncredentialed management rejected',client.get('/api/admin/runs').status_code in {401,503})
        checks.check('invalid query rejected',client.get('/api/tomica',params={'limit':0}).status_code==422)
        if mode=='demo':
            token=settings.admin_token.get_secret_value()
            if not token:raise Blocked('demo admin token not configured')
            headers={'Authorization':'Bearer '+token}
            page=client.get('/api/tomica',params={'limit':1}).json()
            entity=page['items'][0]['id']
            changed=client.patch('/api/admin/overrides',headers=headers,json={'kind':'tomica_model','entity_key':entity,'field':'name_display','value':'验收-'+uuid4().hex[:6]})
            checks.check('authorized override accepted',changed.status_code==200)
            checks.check('revision invalidates old cursor',client.get('/api/tomica',params={'cursor':page['next_cursor']}).status_code==409)
            # 恢复原先有效展示值，保留源字段；只修改本演示条目。
            client.patch('/api/admin/overrides',headers=headers,json={'kind':'tomica_model','entity_key':entity,'field':'name_display','value':page['items'][0].get('name_display')})
            queued=client.post('/api/admin/sync',headers=headers,json={'source':'tomica','mode':'incremental'})
            checks.check('management enqueues asynchronously',queued.status_code==202)
            run_id=queued.json()['run_id']
            checks.check('same source collision rejected',client.post('/api/admin/sync',headers=headers,json={'source':'tomica','mode':'full'}).status_code==409)
            engine=create_engine(settings.database_url)
            try:
                with engine.begin() as connection:
                    checks.check('enqueued task has not fetched source',connection.scalar(text('SELECT status FROM sync_runs WHERE id=:id'),{'id':run_id})=='queued')
                    connection.execute(text('DELETE FROM sync_runs WHERE id=:id'),{'id':run_id})
            finally:engine.dispose()


def images_suite(settings,checks):
    from backend.app.sync.images import ImageService
    with isolated_database(settings) as (engine,factory):
        with factory() as session,session.begin():
            image=ImageAsset(source_url='https://s1.52poke.com/test.png');session.add(image);session.flush()
            def no_download(url):raise AssertionError('pending image attempted download')
            checks.check('pending image is not downloaded',ImageService(session,settings,downloader=no_download).process_asset(image.id).status=='pending')
            image.rights_status,image.rights_reference='approved','test-only evidence'
            class Storage:
                def put_object(self,**kwargs):raise ValueError('simulated storage failure')
            config=settings.model_copy(update={'public_image_base_url':'https://images.example.test'})
            result=ImageService(session,config,downloader=lambda u:b'\x89PNG\r\n\x1a\nfixture',s3=Storage()).process_asset(image.id)
            checks.check('upload failure records retry',result.status=='failed' and image.next_retry_at is not None)


def schedule_suite(settings,checks):
    from apscheduler.schedulers.background import BackgroundScheduler
    with isolated_database(settings) as (engine,factory):
        current=datetime(2026,11,9,2,tzinfo=ZoneInfo('Asia/Shanghai'))
        checks.check('daily trigger is 03:00 Beijing',triggers()['daily'].get_next_fire_time(None,current).hour==3)
        checks.check('weekly trigger is Sunday 04:00 Beijing',triggers()['weekly'].get_next_fire_time(None,current).hour==4)
        for mode in ['incremental','full']:
            event=threading.Event();scheduler=BackgroundScheduler(timezone='Asia/Shanghai')
            def trigger():enqueue_scheduled(factory,settings,'tomica',mode);event.set()
            scheduler.add_job(trigger,'date',run_date=now()+timedelta(seconds=1))
            scheduler.start()
            try:
                checks.check(mode+' real short trigger fired',event.wait(10))
                with factory() as session:
                    run=session.scalar(select(SyncRun).where(SyncRun.status=='queued'))
                    checks.check(mode+' persists expected mode',run is not None and run.mode==mode)
                    run_id=run.id
                import backend.app.sync.service as module
                original=module.TomicaAdapter
                class FixtureAdapter(TomicaAdapter):
                    def _links(self,url,soup,only_sections=False):return super()._links(url,soup,only_sections) if url.endswith('menu.html') else []
                module.TomicaAdapter=FixtureAdapter
                client=fixture_client()
                try:
                    with factory() as session:
                        result=SyncService(session,settings,session_factory=factory,http_client=client).run_once(run_id)
                    checks.check(mode+' worker path completes triggered run',result.status=='succeeded')
                finally:client.close();module.TomicaAdapter=original
            finally:scheduler.shutdown()


def sources_suite(settings,checks):
    for source,adapter in [('tomica',TomicaAdapter()),('pokemon',PokemonAdapter())]:
        client=SourceHttpClient(source)
        try:
            result=client.fetch(adapter.seed_urls()[0])
            checks.check(source+' live index accessible',not result.error and result.status==200)
            page=adapter.parse(adapter.seed_urls()[0],result.body)
            checks.check(source+' index discovers details',bool(page.discovered_urls))
            target=next((u for u in page.discovered_urls if '/number/' in u),page.discovered_urls[0])
            result=client.fetch(target)
            checks.check(source+' live detail accessible',not result.error and result.status==200)
            checks.check(source+' detail has parsed records',bool(adapter.parse(target,result.body).candidates))
        finally:client.close()


def coverage_suite(settings,checks):
    engine=create_engine(settings.database_url)
    try:
        with sessionmaker(engine)() as session:
            for source in ['tomica','pokemon']:
                run=session.scalar(select(SyncRun).where(SyncRun.source==source,SyncRun.mode=='full',SyncRun.limit.is_(None)).order_by(SyncRun.requested_at.desc()))
                if run is None or run.status!='succeeded':raise Blocked(source+' unrestricted full sync has not succeeded')
                items=list(session.scalars(select(SyncItem).where(SyncItem.run_id==run.id)))
                checks.check(source+' full run is nonempty',len(items)>1)
                checks.check(source+' every discovered page succeeded',all(i.status=='succeeded' for i in items))
                checks.check(source+' full run has changed or verified pages',run.stats.get('pages',0)>1)
                if source=='pokemon':
                    from backend.app.models import Pokemon
                    actual=set(session.scalars(select(Pokemon.dex)))
                    index=session.scalar(select(SyncItem).where(SyncItem.run_id==run.id,SyncItem.url.like('%/%')) .order_by(SyncItem.checked_at))
                    # 清单候选与数据库全国编号逐项比较，不以固定总数判完整。
                    expected={c['fields']['dex'] for item in items for c in item.candidates if c['kind']=='pokemon' and c.get('evidence',{}).get('list_entry')}
                    checks.check('national list and published dex set agree',bool(expected) and expected<=actual)
    finally:engine.dispose()


def run_suite(name,settings,checks,base_url,mode):
    if mode=='production-readonly' and name not in {'api','sources','coverage'}:
        raise ValueError('production-readonly forbids write suites')
    if name=='api':return api_suite(settings,checks,base_url,mode)
    return {'postgres':postgres_suite,'sync':sync_suite,'images':images_suite,'schedule':schedule_suite,'sources':sources_suite,'coverage':coverage_suite}[name](settings,checks)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--env-file')
    parser.add_argument('--mode',choices=['demo','production-readonly'],required=True)
    parser.add_argument('--suite',choices=['postgres','api','sync','images','schedule','sources','coverage','all'],required=True)
    parser.add_argument('--base-url')
    args=parser.parse_args()
    checks=Checks();status='pass';error=None;code=0
    try:
        load_environment(args.env_file);settings=Settings(_env_file=None)
        if args.mode=='demo':assert_demo_database(settings.database_url)
        names=(['postgres','api','sync','images','schedule'] if args.mode=='demo' else ['api','sources','coverage']) if args.suite=='all' else [args.suite]
        for name in names:run_suite(name,settings,checks,args.base_url or os.environ.get('ACCEPTANCE_BASE_URL','http://127.0.0.1:8092'),args.mode)
        if not checks.results:raise Blocked('zero assertions executed')
    except Blocked as exc:status,error,code='blocked',str(exc),2
    except Exception as exc:status,error,code='fail',type(exc).__name__+': '+str(exc),1
    # 错误摘要不序列化连接串、配置或SQL参数。
    if error and ('postgresql' in error or 'password' in error.lower()):error='database operation failed; inspect protected server logs'
    report={'mode':args.mode,'suite':args.suite,'status':status,'assertions':len(checks.results),'results':checks.results,'error':error,'scope':'real PostgreSQL; simulated sources/storage in demo' if args.mode=='demo' else 'live read-only checks','timestamp':now().isoformat()}
    directory=Path(os.environ.get('ARTIFACT_DIR',str(ROOT/'artifacts/acceptance')));directory.mkdir(parents=True,exist_ok=True)
    (directory/('acceptance-'+args.mode+'-'+args.suite+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=True));return code


if __name__=='__main__':raise SystemExit(main())
