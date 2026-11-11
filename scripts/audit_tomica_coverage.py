"""Read-only coverage and cache evidence for the latest Tomica reconciliation."""
from collections import Counter
import json
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, load_only

from backend.app.config import Settings
from backend.app.models import ImageAsset, SourceIdentity, SourcePage, SyncItem, SyncRun, TomicaModel
from backend.app.reference_images import read_reference
from backend.app.repository import CatalogRepository
from scripts.repair_tomica_editions import suspicious_names


def main():
    settings = Settings()
    engine = create_engine(settings.database_url)
    try:
        with Session(engine) as session:
            latest = session.scalar(select(SyncRun).where(SyncRun.source == 'tomica', SyncRun.mode == 'full').order_by(SyncRun.requested_at.desc()))
            pages = list(session.scalars(select(SourcePage).options(load_only(SourcePage.url)).where(SourcePage.source == 'tomica')))
            items = list(session.scalars(select(SyncItem).options(load_only(SyncItem.url, SyncItem.status, SyncItem.issues)).where(SyncItem.run_id == latest.id))) if latest else []
            recent = session.scalars(select(SyncItem).join(SyncRun, SyncRun.id == SyncItem.run_id).options(load_only(SyncItem.url, SyncItem.status, SyncItem.issues)).where(SyncRun.source == 'tomica', SyncRun.requested_at >= latest.requested_at).order_by(SyncRun.requested_at.desc(), SyncItem.checked_at.desc())) if latest else []
            latest_checks = {}
            for item in recent:
                latest_checks.setdefault(item.url, item)
            directory = Path(settings.artifact_dir).parent / 'reference-images'
            editions = session.scalar(select(func.count()).select_from(SourceIdentity).where(SourceIdentity.source == 'tomica', SourceIdentity.kind == 'tomica_model', SourceIdentity.source_key.like('edition:%')))
            image_ids = set(session.scalars(select(TomicaModel.primary_image_id).where(TomicaModel.source_locator.like('edition:%')))) - {None}
            cached, missing, ready_ids = 0, [], set()
            dream_ids = set(session.scalars(select(TomicaModel.primary_image_id).where(TomicaModel.source_url == 'http://tomica.minibird.jp/t-tomica/event/tiv%20dori-mutomica.html'))) - {None}
            repo = CatalogRepository(session)
            for image_id in image_ids:
                url = repo.image(image_id)['source_image_url']
                if url and read_reference(image_id, url, directory) is not None:
                    cached += 1
                    ready_ids.add(image_id)
                else:
                    missing.append(image_id)
            report = {'run': {'id': latest.id, 'status': latest.status, 'stats': latest.stats} if latest else None,
                      'source_pages': len(pages), 'directories': dict(Counter(urlsplit(p.url).path.split('/')[2] for p in pages)),
                      'run_items': dict(Counter(i.status for i in items)),
                      'problems': [{'url': i.url, 'status': i.status, 'issue_counts': dict(Counter(v['code'] for v in i.issues)), 'issues': [v for v in i.issues if v['code'] in {'FETCH_OR_PARSE_FAILED', 'IDENTITY_AMBIGUOUS', 'COUNT_DROP', 'DISCOVERY_DROP'}][:30]} for i in items if i.status in {'failed', 'isolated'}],
                      'caption_problems': [{'url': i.url, 'count': sum(v['code'] == 'SUPPLEMENT_CAPTION_MISSING' for v in i.issues), 'sample': [v for v in i.issues if v['code'] == 'SUPPLEMENT_CAPTION_MISSING'][:10]} for i in latest_checks.values() if any(v['code'] == 'SUPPLEMENT_CAPTION_MISSING' for v in i.issues)],
                      'total_models': session.scalar(select(func.count()).select_from(TomicaModel)), 'edition_models': editions,
                      'edition_covers': len(image_ids), 'edition_covers_cached_on_disk': cached, 'edition_covers_pending': len(missing),
                      'dream_page_covers': len(dream_ids), 'dream_page_covers_cached': len(dream_ids & ready_ids),
                      'suspect_name_pages': sorted(set(session.scalars(select(TomicaModel.source_url).where(suspicious_names())))),
                      'pending_cover_sample': missing[:30],
                      'original_image_assets': session.scalar(select(func.count()).select_from(ImageAsset))}
            target = Path(settings.artifact_dir) / 'tomica-coverage.json'
            target.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
            print(json.dumps(report, ensure_ascii=True, default=str))
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
