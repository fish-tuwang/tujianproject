"""Publish cached source facts without rewriting existing basic catalog data."""
import argparse
import json
from pathlib import Path
import time
from bs4 import BeautifulSoup
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session
from backend.app.config import Settings
from backend.app.models import Pokemon, PokemonDetail
from backend.app.repository import CatalogRepository
from backend.app.schemas import ParsedPage, SourceCandidate
from backend.app.sources.pokemon_details import parse_details
from backend.app.sync.service import SyncService


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--watch', action='store_true')
    parser.add_argument('--missing-only', action='store_true')
    parser.add_argument('--dex', type=int, action='append', help='Refresh only the specified national number; repeatable')
    args = parser.parse_args()
    settings = Settings()
    engine = create_engine(settings.database_url)
    root = Path(settings.artifact_dir).parent / 'pokemon-detail-html'
    report = {'published': 0, 'failed': []}
    processed = set()
    with engine.connect() as lease:
        if not lease.scalar(text('SELECT pg_try_advisory_lock(71003)')):
            raise RuntimeError('Enrichment backfill already running')
        lease.commit()
        with Session(engine) as session:
            catalog = dict(session.execute(select(Pokemon.dex, Pokemon.source_url)).all())
            if args.dex:
                if any(dex not in catalog for dex in args.dex):
                    raise ValueError('National number not found')
                catalog = {dex: url for dex, url in catalog.items() if dex in args.dex}
            if args.missing_only:
                processed.update(row.dex for row in session.scalars(select(PokemonDetail).execution_options(yield_per=25)) if row.dex in catalog and all(row.data.get(key) for key in ['base_stats', 'acquisition', 'matchups', 'movesets', 'shiny_pairs']))
                report['existing'] = len(processed)
        while True:
            for path in sorted(root.glob('*.html')):
                dex = int(path.stem)
                if dex in processed or dex not in catalog:
                    continue
                try:
                    data = parse_details(BeautifulSoup(path.read_text(encoding='utf-8'), 'html.parser'), catalog[dex])
                    if not data['base_stats']:
                        raise ValueError('Missing base stats')
                    candidate = SourceCandidate(kind='pokemon_detail', source_key=str(dex), fields={'dex': dex, 'data': data, 'source_url': catalog[dex]}, evidence={'url': catalog[dex]})
                    with Session(engine) as session, session.begin():
                        repo = CatalogRepository(session)
                        page = ParsedPage(source='pokemon', url=catalog[dex], candidates=[candidate])
                        SyncService(session, settings).attach_images(page, session)
                        if repo.publish_candidates(None, [candidate], source='pokemon'):
                            repo.bump_revision('pokemon')
                    report['published'] += 1
                except Exception as error:
                    report['failed'].append({'dex': dex, 'error': str(error)[:200]})
                processed.add(dex)
                if len(processed) % 25 == 0:
                    print(json.dumps(report), flush=True)
                (root / 'backfill-progress.json').write_text(json.dumps(report), encoding='utf-8')
            if not args.watch or len(processed) == len(catalog):
                break
            progress = root / 'progress.json'
            if progress.exists():
                fetch = json.loads(progress.read_text())
                if fetch['saved'] + fetch['existing'] + len(fetch['failed']) == len(catalog):
                    break
            time.sleep(5)
        with Session(engine) as session:
            coverage = dict.fromkeys(['base_stats', 'acquisition', 'matchups', 'movesets', 'shiny_pairs'], 0)
            count = 0
            stored = set()
            for row in session.scalars(select(PokemonDetail).execution_options(yield_per=25)):
                count += 1
                stored.add(row.dex)
                for key in coverage:
                    coverage[key] += bool(row.data.get(key))
            report.update(records=count, coverage=coverage, target_records=len(catalog), missing=sorted(set(catalog) - stored))
        print(json.dumps(report), flush=True)
        (root / 'backfill-result.json').write_text(json.dumps(report), encoding='utf-8')
        if report['failed'] or report['missing']:
            raise SystemExit(1)


if __name__ == '__main__':
    main()
