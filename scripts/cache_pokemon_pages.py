"""Fetch source details serially for the six-section enrichment backfill."""
import json
from pathlib import Path
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from backend.app.config import Settings
from backend.app.models import Pokemon
from backend.app.sources.http import SourceHttpClient
from backend.app.sync.service import SourceLockProvider


def main():
    settings = Settings()
    engine = create_engine(settings.database_url)
    root = Path(settings.artifact_dir).parent / 'pokemon-detail-html'
    root.mkdir(parents=True, exist_ok=True)
    lease = SourceLockProvider(engine).acquire('pokemon')
    if lease is None:
        raise RuntimeError('Pokemon source busy; retry after the active sync')
    client = SourceHttpClient('pokemon')
    report = {'saved': 0, 'existing': 0, 'failed': []}
    try:
        with Session(engine) as session:
            rows = list(session.execute(select(Pokemon.dex, Pokemon.source_url).order_by(Pokemon.dex)))
        for dex, url in rows:
            lease.assert_alive()
            target = root / f'{dex:04d}.html'
            if target.exists():
                report['existing'] += 1
                continue
            result = client.fetch(url)
            if result.error:
                report['failed'].append({'dex': dex, 'error': result.error})
            else:
                pending = target.with_suffix('.tmp')
                pending.write_bytes(result.body)
                pending.replace(target)
                report['saved'] += 1
            (root / 'progress.json').write_text(json.dumps(report), encoding='utf-8')
            if dex % 25 == 0:
                print(json.dumps({'dex': dex, **report}), flush=True)
        (root / 'progress.json').write_text(json.dumps(report), encoding='utf-8')
        print(json.dumps(report), flush=True)
        if report['failed']:
            raise SystemExit(1)
    finally:
        client.close()
        lease.close()


if __name__ == '__main__':
    main()
