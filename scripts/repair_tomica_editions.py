"""Recheck actual source pages for encoding errors and unlabelled shared photos."""
import argparse
import json
from pathlib import Path
import unicodedata

from sqlalchemy import create_engine, delete, or_, select
from sqlalchemy.orm import sessionmaker

from backend.app.audit import audit, configure_audit
from backend.app.config import Settings
from backend.app.models import FieldOverride, SourceIdentity, SourcePage, SyncRun, TomicaModel, TomicaVariant, now
from backend.app.repository import CatalogRepository
from backend.app.sources.http import SourceHttpClient
from backend.app.sources.tomica import TomicaAdapter
from backend.app.sync.service import SourceLockProvider, SyncService


def suspicious_names():
    markers = ['�', '繝', '繧', '縺', '縲']
    markers += [unicodedata.normalize('NFKC', text.encode('utf-8').decode('cp932', errors='replace')) for text in ['特注', 'ギフトセット', 'キャラクター', 'イベント', '非売品']]
    return or_(*(TomicaModel.name_original.contains(marker) for marker in markers))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--urls-file', type=Path, help='Explicit source pages requiring a verified caption recheck')
    args = parser.parse_args()
    settings = Settings()
    configure_audit(Path(settings.artifact_dir).parent / 'logs', channels={'collection'})
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    factory = sessionmaker(engine, expire_on_commit=False)
    lease = SourceLockProvider(engine).acquire('tomica')
    if lease is None:
        raise RuntimeError('Tomica source is still processing; do not interrupt it')
    client = SourceHttpClient('tomica', interval=settings.source_interval_seconds)
    report = {'mode': 'apply' if args.apply else 'dry-run', 'pages': [], 'removed_models': [], 'counts': {'created': 0, 'updated': 0}}
    target = Path(settings.artifact_dir) / ('edition-caption-repair.json' if args.apply else 'edition-caption-repair-preview.json')
    run_id = None

    def save():
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
        target.chmod(0o640)

    try:
        with factory() as session:
            shared = list(session.scalars(select(SourceIdentity).where(SourceIdentity.source == 'tomica', SourceIdentity.kind == 'tomica_model', SourceIdentity.source_key.like('edition:%'))))
            shared = [i for i in shared if i.evidence.get('group') and i.evidence.get('caption') == i.evidence['group'] and not i.evidence.get('description')]
            urls = set(session.scalars(select(TomicaModel.source_url).where(suspicious_names())))
            urls.update(i.evidence['url'] for i in shared)
            if args.urls_file:
                requested = json.loads(args.urls_file.read_text(encoding='utf-8'))
                if not isinstance(requested, list) or not all(isinstance(url, str) for url in requested):
                    raise ValueError('Expected a JSON list of source URLs')
                urls.update(requested)
            shared_by_page = {url: {i.source_key for i in shared if i.evidence['url'] == url} for url in urls}
        if args.apply:
            with factory() as session, session.begin():
                run = SyncRun(source='tomica', mode='incremental', status='running')
                session.add(run)
                session.flush()
                run_id = run.id
            audit('run_started', source='tomica', run_id=run_id, mode='incremental', scope='verified_encoding_and_caption_repair')
        for url in sorted(urls):
            fetched = client.fetch(url)
            if fetched.error:
                raise RuntimeError(url + ': ' + fetched.error)
            parsed = TomicaAdapter().parse(url, fetched.body)
            keys = {c.source_key for c in parsed.candidates if c.kind == 'tomica_model'}
            obsolete = shared_by_page[url] - keys
            summary = {'url': url, 'http_status': fetched.status, 'models': len(keys), 'remove_shared_only': sorted(obsolete)}
            report['pages'].append(summary)
            save()
            print(json.dumps(summary, ensure_ascii=True), flush=True)
            if not args.apply:
                continue
            changes, removed = [], []
            with factory() as handle:
                service = SyncService(handle, settings, session_factory=factory)
                service.validate_page(parsed)
                with service._checkpoint(lease) as session:
                    repo = CatalogRepository(session)
                    for key in obsolete:
                        identity = session.scalar(select(SourceIdentity).where(SourceIdentity.source == 'tomica', SourceIdentity.kind == 'tomica_model', SourceIdentity.source_key == key))
                        if identity is None:
                            continue
                        model = session.get(TomicaModel, identity.entity_id)
                        variants = list(session.scalars(select(TomicaVariant).where(TomicaVariant.model_id == model.id)))
                        ids = [model.id] + [v.id for v in variants]
                        if session.scalar(select(FieldOverride.id).where(FieldOverride.entity_key.in_(ids))):
                            raise RuntimeError('manual correction found; keep the edition: ' + key)
                        snapshot = {'model': {c.name: getattr(model, c.name) for c in model.__table__.columns}, 'variants': [{c.name: getattr(v, c.name) for c in v.__table__.columns} for v in variants], 'identity': identity.evidence}
                        report['removed_models'].append(snapshot)
                        save()  # Preserve exact records before deleting only these new editions.
                        session.execute(delete(SourceIdentity).where(SourceIdentity.source == 'tomica', SourceIdentity.entity_id.in_(ids), SourceIdentity.source_key.like('edition:%')))
                        for variant in variants:
                            session.delete(variant)
                        session.flush()
                        session.delete(model)
                        removed.append({'entity_id': model.id, 'source_key': key, 'name': model.name_original})
                    staged = repo.stage_page(run_id, parsed)
                    service.attach_images(parsed, session)
                    changed = repo.publish_candidates(run_id, parsed.candidates, source='tomica', changes=changes)
                    changed += service.link_model_images(session, parsed)
                    if changed or removed:
                        repo.bump_revision('tomica')
                    page = session.scalar(select(SourcePage).where(SourcePage.source == 'tomica', SourcePage.url == url))
                    page.accepted_count, page.content_hash = len(parsed.candidates), fetched.content_hash
                    page.etag, page.last_modified, page.discovered_urls = fetched.etag, fetched.last_modified, parsed.discovered_urls
                    page.checked_at, page.last_success_at = now(), now()
                    staged.status, staged.checked_at, staged.attempts = 'succeeded', now(), 1
            for change in changes:
                report['counts'][change['action']] += 1
                audit('record_' + change['action'], source='tomica', run_id=run_id, url=url, **change)
            for entry in removed:
                audit('record_removed', source='tomica', run_id=run_id, url=url, reason='shared heading has no individual product name', **entry)
            audit('page_checked', source='tomica', run_id=run_id, url=url, http_status=fetched.status, status='succeeded', scope='verified_encoding_and_caption_repair', removed_models=len(removed), changes=len(changes))
        if args.apply:
            with factory() as session, session.begin():
                run = session.get(SyncRun, run_id)
                run.status, run.finished_at = 'succeeded', now()
                run.stats = {'scope': 'targeted_caption_repair', 'pages': len(report['pages']), **report['counts'], 'removed_models': len(report['removed_models'])}
            audit('run_finished', source='tomica', run_id=run_id, scope='verified_encoding_and_caption_repair', status='succeeded', complete=False)
        with factory() as session:
            report['remaining_suspect_pages'] = sorted(set(session.scalars(select(TomicaModel.source_url).where(suspicious_names()))))
        if args.apply and report['remaining_suspect_pages']:
            report['status'] = 'partial'
            save()
            raise RuntimeError('source names still need review: ' + ', '.join(report['remaining_suspect_pages']))
        report.update(status='pass', run_id=run_id)
        save()
        print(json.dumps({k:v for k,v in report.items() if k != 'removed_models'}, ensure_ascii=True), flush=True)
    except Exception:
        if run_id:
            with factory() as session, session.begin():
                run = session.get(SyncRun, run_id)
                run.status, run.finished_at = 'failed', now()
        raise
    finally:
        client.close()
        lease.close()
        engine.dispose()


if __name__ == '__main__':
    main()
