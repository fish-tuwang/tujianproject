"""Repair only image links, with a reversible before/after journal."""
import argparse
import json
from pathlib import Path
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from backend.app.config import Settings
from backend.app.models import ImageAsset, Pokemon, PokemonForm, SourceIdentity, SyncItem, SyncRun, TomicaModel
from backend.app.repository import CatalogRepository
from backend.app.sources.http import SourceHttpClient
from backend.app.sources.pokemon import PokemonAdapter
from backend.app.sync.service import SourceLockProvider


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--section', choices=['covers', 'forms'], required=True)
    args = parser.parse_args()
    settings = Settings()
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    source = 'tomica' if args.section == 'covers' else 'pokemon'
    lease = SourceLockProvider(engine).acquire(source)
    if lease is None:
        raise RuntimeError('source busy; no images changed')
    directory = Path(settings.artifact_dir)
    directory.mkdir(parents=True, exist_ok=True)
    journal_path = directory / ('image-repair-' + args.section + '.json')
    report = {'section': args.section, 'status': 'running', 'changes': [], 'errors': []}
    def journal():
        journal_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    def change(row, field, value, kind):
        if value and getattr(row, field) != value:
            report['changes'].append({'kind': kind, 'id': row.id, 'field': field, 'before': getattr(row, field), 'after': value})
            journal()  # Persist recovery evidence before committing the field change.
            setattr(row, field, value)
            return True
        return False
    try:
        if args.section == 'covers':
            with Session(lease.connection) as session, session.begin():
                identities = {i.source_key: i.entity_id for i in session.scalars(select(SourceIdentity).where(SourceIdentity.source == 'tomica', SourceIdentity.kind == 'tomica_model'))}
                images = {i.source_url: i.id for i in session.scalars(select(ImageAsset))}
                seen = set()
                items = session.scalars(select(SyncItem).join(SyncRun, SyncRun.id == SyncItem.run_id).where(SyncRun.source == 'tomica', SyncItem.url.like('%/number/%'), SyncItem.status.in_(['succeeded', 'isolated'])).order_by(SyncRun.requested_at.desc(), SyncItem.checked_at.desc()))
                for item in items:
                    for candidate in item.candidates:
                        if candidate['kind'] != 'tomica_variant':
                            continue
                        key = candidate.get('evidence', {}).get('model_key')
                        model_id = identities.get(key)
                        image_id = images.get(candidate.get('evidence', {}).get('image_url'))
                        if not model_id or model_id in seen or not image_id:
                            continue
                        seen.add(model_id)
                        change(session.get(TomicaModel, model_id), 'primary_image_id', image_id, 'tomica_model')
                if report['changes']:
                    CatalogRepository(session).bump_revision('tomica')
        else:
            with Session(lease.connection) as session, session.begin():
                for form in session.scalars(select(PokemonForm).where(PokemonForm.form_key == 'default')):
                    pokemon = session.scalar(select(Pokemon).where(Pokemon.dex == form.dex))
                    if pokemon:
                        change(form, 'image_id', pokemon.primary_image_id, 'pokemon_form')
                targets = list(session.scalars(select(Pokemon).where(Pokemon.dex.in_(select(PokemonForm.dex).where(PokemonForm.form_key != 'default', PokemonForm.image_id.is_(None)))).order_by(Pokemon.dex)))
                targets = [(p.dex, p.source_url) for p in targets]
                if report['changes']:
                    CatalogRepository(session).bump_revision('pokemon')
            client = SourceHttpClient('pokemon')
            try:
                for index, (dex, url) in enumerate(targets):
                    lease.assert_alive()
                    result = client.fetch(url)
                    if result.error:
                        report['errors'].append({'dex': dex, 'error': result.error})
                        continue
                    parsed = PokemonAdapter().parse(url, result.body)
                    with Session(lease.connection) as session, session.begin():
                        changed = False
                        for candidate in parsed.candidates:
                            if candidate.kind != 'pokemon_form' or not candidate.evidence.get('image_url'):
                                continue
                            form = session.scalar(select(PokemonForm).where(PokemonForm.dex == dex, PokemonForm.form_key == candidate.fields['form_key']))
                            if form is None:
                                continue
                            image_url = candidate.evidence['image_url']
                            image = session.scalar(select(ImageAsset).where(ImageAsset.source_url == image_url))
                            if image is None:
                                image = ImageAsset(source_url=image_url)
                                session.add(image)
                                session.flush()
                            changed |= change(form, 'image_id', image.id, 'pokemon_form')
                        if changed:
                            CatalogRepository(session).bump_revision('pokemon')
                    print(json.dumps({'dex': dex, 'processed': index + 1, 'targets': len(targets), 'changed': len(report['changes'])}), flush=True)
            finally:
                client.close()
        report['status'] = 'partial' if report['errors'] else 'completed'
        journal()
        print(json.dumps({'section': args.section, 'status': report['status'], 'changes': len(report['changes']), 'errors': report['errors']}), flush=True)
        return 0 if not report['errors'] else 1
    finally:
        lease.close()
        engine.dispose()


if __name__ == '__main__':
    raise SystemExit(main())
