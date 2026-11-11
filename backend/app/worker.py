import argparse
from dataclasses import asdict
import json
import logging
from pathlib import Path
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from alembic import command
from alembic.config import Config
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from backend.app.config import ROOT, Settings
from backend.app.audit import audit, configure_audit
from backend.app.models import CatalogRevision, ImageAsset, Pokemon, SourcePage, SyncItem, SyncRun, now
from backend.app.repository import CatalogError, CatalogRepository
from backend.app.schemas import SourceCandidate
from backend.app.sources.http import SourceHttpClient
from backend.app.sources.tomica import TomicaAdapter
from backend.app.sources.pokemon import PokemonAdapter
from backend.app.sync.images import ImageService
from backend.app.sync.service import SyncService


def initialize(settings):
    config = Config(str(ROOT / 'backend/alembic.ini'))
    config.attributes['database_url'] = settings.database_url
    command.upgrade(config, 'head')


def seed_demo(session, settings):
    if make_url(settings.database_url).database != 'dual_catalog_demo':
        raise ValueError('demo seed refused: database must be dual_catalog_demo')
    data = json.loads((ROOT / 'backend/tests/fixtures/demo.json').read_text(encoding='utf-8'))
    repo = CatalogRepository(session)
    for source in ['tomica', 'pokemon']:
        candidates = [SourceCandidate(**c) for c in data['candidates'] if (c['kind'].startswith('tomica')) == (source == 'tomica')]
        changed = repo.publish_candidates(None, candidates, source=source)
        if changed:
            repo.bump_revision(source)
    return {'dataset': 'synthetic-demo', 'records': len(data['candidates'])}


def enqueue_scheduled(factory, settings, source, mode):
    with factory() as session, session.begin():
        run = session.scalar(select(SyncRun).where(SyncRun.source == source, SyncRun.status.in_(['queued', 'running'])))
        if run:
            if mode == 'full':
                if run.status == 'queued':
                    run.mode = 'full'
                else:
                    run.followup_mode = 'full'
            return run.id
        return SyncService(session, settings, session_factory=factory).enqueue_run(source, mode)


def triggers():
    return {'daily': CronTrigger(hour=3, minute=0, timezone='Asia/Shanghai'), 'weekly': CronTrigger(day_of_week='sun', hour=4, minute=0, timezone='Asia/Shanghai')}


def build_scheduler(factory, settings):
    scheduler = BlockingScheduler(timezone='Asia/Shanghai', job_defaults={'coalesce': True, 'max_instances': 1, 'misfire_grace_time': 3600})
    for source in ['tomica', 'pokemon']:
        for name, trigger in triggers().items():
            scheduler.add_job(enqueue_scheduled, trigger, args=[factory, settings, source, 'full' if name == 'weekly' else 'incremental'], id=f'{source}-{name}', replace_existing=True)
    return scheduler


def report(factory):
    with factory() as session:
        runs = list(session.scalars(select(SyncRun).order_by(SyncRun.requested_at.desc()).limit(20)))
        value = {'runs': [{'id': r.id, 'source': r.source, 'mode': r.mode, 'status': r.status, 'limit': r.limit, 'complete': r.status == 'succeeded' and r.mode == 'full' and r.limit is None, 'stats': r.stats, 'last_error': r.last_error} for r in runs], 'pages': len(list(session.scalars(select(SourcePage.id))))}
        value['next_triggers'] = {k: str(t.get_next_fire_time(None, datetime.now(ZoneInfo('Asia/Shanghai')))) for k, t in triggers().items()}
        return value


def work_once(factory, settings):
    with factory() as session:
        service = SyncService(session, settings, session_factory=factory)
        run_id = service.claim_next_run()
        if run_id:
            return service.run_once(run_id)
    with factory() as session, session.begin():
        due = session.scalar(select(SyncItem).where(SyncItem.status == 'failed', SyncItem.next_retry_at <= now(), SyncItem.attempts < 3))
        if due:
            run = session.get(SyncRun, due.run_id)
            active = session.scalar(select(SyncRun.id).where(SyncRun.source == run.source, SyncRun.status.in_(['queued', 'running'])))
            if not active:
                run.status, due.status = 'queued', 'pending'
                due.next_retry_at = None
                return None
        image = session.scalar(select(ImageAsset).where(ImageAsset.rights_status == 'approved', ImageAsset.status != 'ready', ImageAsset.attempts < 3, (ImageAsset.next_retry_at.is_(None)) | (ImageAsset.next_retry_at <= now())))
        if image:
            ImageService(session, settings).process_asset(image.id)
    return None


def main():
    parser = argparse.ArgumentParser(description='Dual catalog persistent worker')
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ['init-db', 'work', 'schedule', 'probe', 'report']:
        sub.add_parser(name)
    demo = sub.add_parser('seed-demo')
    demo.add_argument('--confirm-demo', action='store_true', required=True)
    sync = sub.add_parser('sync')
    sync.add_argument('--source', choices=['tomica', 'pokemon'], required=True)
    sync.add_argument('--mode', choices=['incremental', 'full'], default='incremental')
    sync.add_argument('--limit', type=int)
    args = parser.parse_args()
    settings = Settings()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    configure_audit(Path(settings.artifact_dir).parent / 'logs', channels={'collection'})
    audit('process_started', command=args.command)
    if args.command == 'init-db':
        initialize(settings)
        print(json.dumps({'migration': 'head', 'status': 'ready'}))
        return 0
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    factory = sessionmaker(engine, expire_on_commit=False)
    try:
        if args.command == 'seed-demo':
            with factory() as session, session.begin():
                print(json.dumps(seed_demo(session, settings)))
        elif args.command == 'sync':
            with factory() as session, session.begin():
                service = SyncService(session, settings, session_factory=factory)
                existing = session.scalar(select(SyncRun).where(SyncRun.source == args.source, SyncRun.status.in_(['queued', 'running']), SyncRun.mode == args.mode))
                run_id = existing.id if existing else service.enqueue_run(args.source, args.mode, args.limit)
            result = service.run_once(run_id)
            print(json.dumps(asdict(result)))
            return 0 if result.status in {'succeeded', 'limited'} else 1
        elif args.command == 'work':
            while True:
                try:
                    result = work_once(factory, settings)
                    if result:
                        print(json.dumps(asdict(result)), flush=True)
                except Exception:
                    logging.exception('worker task failed')
                time.sleep(2)
        elif args.command == 'schedule':
            build_scheduler(factory, settings).start()
        elif args.command == 'report':
            print(json.dumps(report(factory)))
        elif args.command == 'probe':
            value = []
            for source, adapter in [('tomica', TomicaAdapter()), ('pokemon', PokemonAdapter())]:
                client = SourceHttpClient(source)
                try:
                    for url in adapter.seed_urls():
                        result = client.fetch(url)
                        page = adapter.parse(url, result.body) if not result.error else None
                        value.append({'source': source, 'status': result.status, 'error': result.error, 'candidates': len(page.candidates) if page else 0})
                        if page and page.discovered_urls:
                            detail = client.fetch(page.discovered_urls[0])
                            value.append({'source': source, 'detail_status': detail.status, 'error': detail.error})
                finally:
                    client.close()
            print(json.dumps(value))
            return int(any(v.get('error') for v in value))
        return 0
    finally:
        engine.dispose()


if __name__ == '__main__':
    raise SystemExit(main())
