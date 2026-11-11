"""Prepare an isolated local browser fixture using read-only public catalog rows."""
import argparse
from datetime import datetime
import json
import os

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.config import ROOT, Settings
from backend.app.models import ImageAsset, Pokemon, TomicaModel
from backend.app.reference_images import reference_path
from backend.app.worker import initialize
from scripts.seed_tomica_news import import_articles, load_articles


def copy_fields(model, value):
    fields = {column.name: value[column.name] for column in model.__table__.columns if column.name in value}
    for key in ['checked_at', 'updated_at']:
        if isinstance(fields.get(key), str):
            fields[key] = datetime.fromisoformat(fields[key].replace('Z', '+00:00'))
    return fields


def prepare():
    directory = ROOT / 'artifacts/news-demo'
    directory.mkdir(parents=True, exist_ok=True)
    settings = Settings(_env_file=None, database_url='sqlite:///' + (directory / 'catalog.db').as_posix(),
                        artifact_dir=str(directory / 'acceptance'), redis_url='')
    initialize(settings)
    engine = create_engine(settings.database_url)
    originals = []
    try:
        with httpx.Client(base_url='http://117.72.11.77', timeout=90) as client:
            cars = []
            for page in [1, 2]:
                response = client.get('/api/tomica', params={'page': page, 'limit': 100})
                response.raise_for_status()
                cars.extend(response.json()['items'])
            pokemon = []
            for dex in [25, 37]:
                response = client.get('/api/pokemon/' + str(dex))
                response.raise_for_status()
                pokemon.append(response.json())
            with Session(engine) as session, session.begin():
                for model, rows in [(TomicaModel, cars), (Pokemon, pokemon)]:
                    for value in rows:
                        fields = copy_fields(model, value)
                        asset_id, url = value.get('primary_image_id'), value.get('source_image_url')
                        if asset_id and url and session.get(ImageAsset, asset_id) is None:
                            session.add(ImageAsset(id=asset_id, source_url=url))
                        existing = session.get(model, fields['id'])
                        if existing is None:
                            session.add(model(**fields))
                stats = import_articles(session, load_articles(ROOT / 'backend/data/tomica-news'))
            image_directory = directory / 'reference-images'
            image_directory.mkdir(exist_ok=True)
            for value in [v for v in cars if v.get('source_image_url')][:5]:
                response = client.get(value['preview_image_url'])
                response.raise_for_status()
                target = reference_path(value['primary_image_id'], value['source_image_url'], image_directory)
                target.write_bytes(response.content)
                originals.append(value['primary_image_id'])
        print(json.dumps({'database': 'isolated local SQLite', 'tomica_rows': len(cars), 'pokemon_rows': len(pokemon),
                          'old_covers_ready': len(originals), 'news': stats}), flush=True)
    finally:
        engine.dispose()
    return settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serve', action='store_true')
    args = parser.parse_args()
    settings = prepare()
    if args.serve:
        os.environ.update(DATABASE_URL=settings.database_url, ARTIFACT_DIR=settings.artifact_dir, REDIS_URL='')
        import uvicorn
        from backend.app.main import app
        uvicorn.run(app, host='127.0.0.1', port=8094)


if __name__ == '__main__':
    main()
