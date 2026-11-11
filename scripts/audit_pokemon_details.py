"""Read-only coverage and consistency audit for the deployed enrichment."""
import json
from pathlib import Path
import re
from urllib.parse import unquote
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from backend.app.config import Settings
from backend.app.models import ImageAsset, Pokemon, PokemonDetail


def main():
    settings = Settings()
    engine = create_engine(settings.database_url)
    keys = ['base_stats', 'acquisition', 'matchups', 'movesets', 'shiny_pairs']
    report = {'status': 'fail', 'coverage': dict.fromkeys(keys, 0), 'empty': {key: [] for key in keys}, 'errors': []}
    with Session(engine) as session:
        catalog = set(session.scalars(select(Pokemon.dex)))
        stored = set(session.scalars(select(PokemonDetail.dex)))
        assets = dict(session.execute(select(ImageAsset.id, ImageAsset.source_url)).all())
        report.update(expected=len(catalog), records=len(stored), missing=sorted(catalog - stored), machine_records=0, shiny_form_pairs=0)
        for row in session.scalars(select(PokemonDetail).execution_options(yield_per=25)):
            data = row.data
            for key in keys:
                if data.get(key):
                    report['coverage'][key] += 1
                else:
                    report['empty'][key].append(row.dex)
            for group in data.get('base_stats', []):
                if len(group['stats']) != 6 or sum(s['value'] for s in group['stats']) != group['total'] or any(not 0 <= s['value'] <= 255 for s in group['stats']):
                    report['errors'].append({'dex': row.dex, 'issue': 'Invalid base stat group'})
            for pair in data.get('shiny_pairs', []):
                normal = assets.get(pair.get('normal_image_id'))
                shiny = assets.get(pair.get('shiny_image_id'))
                left = re.search(r'HOME_[^/]+\.(?:png|webp)', unquote(normal or ''))
                right = re.search(r'HOME_[^/]+\.(?:png|webp)', unquote(shiny or ''))
                if not left or not right or right[0].replace('_s.', '.') != left[0] or normal != pair['normal_source_url'] or shiny != pair['shiny_source_url']:
                    report['errors'].append({'dex': row.dex, 'issue': 'Unpaired shiny image'})
            report['machine_records'] += any(g['kind'] == 'machine' for g in data.get('movesets', []))
            report['shiny_form_pairs'] += len(data.get('shiny_pairs', []))
        report['status'] = 'pass' if not report['missing'] and not report['errors'] and all(report['coverage'][key] == len(catalog) for key in keys) else 'fail'
    target = Path(settings.artifact_dir) / 'pokemon-details-audit.json'
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False), flush=True)
    engine.dispose()
    return 0 if report['status'] == 'pass' else 1


if __name__ == '__main__':
    raise SystemExit(main())
