"""Authenticated, read-only official Tomica catalogue and cache coverage."""
import hashlib
import json

from fastapi import APIRouter, Request
from sqlalchemy import func, select

from .models import SourceIdentity, TomicaModel, TomicaVariant
from .tomica_mall_backfill import INVENTORY, SEED_FILE, CN_FILE, CN_PACKAGING

router = APIRouter(prefix='/api/tomica-maintenance')


@router.get('')
def coverage(request: Request):
    tables = []
    official = None
    with request.app.state.engine.connect() as connection:
        for model in (TomicaModel, TomicaVariant):
            tables.append({'name': model.__tablename__,
                'count': connection.scalar(select(func.count()).select_from(model))})
        try:
            from .tomica_official import SOURCE
        except ImportError:
            SOURCE = None
        if SOURCE is not None:
            products = list(connection.scalars(select(SourceIdentity.evidence).where(
                SourceIdentity.source == SOURCE, SourceIdentity.kind == 'product',
                SourceIdentity.needs_review.is_(False))))
            official = {'products': len(products),
                'gallery_images': sum(len(p.get('images', [])) for p in products),
                'verified_packaging_products': sum(p.get('packaging_status') == 'verified' for p in products)}
    body = INVENTORY.read_bytes()
    data = json.loads(body)
    seed = SEED_FILE.read_bytes() if SEED_FILE.exists() else b''
    return {'tables': tables, 'official': official,
        'inventory': {'products': len(data['products']), 'categories': len(data['category_counts']),
            'pages': len(data['listing_pages']), 'recorded_images': sum(len(p['images']) for p in data['products']),
            'cached_image_urls': len(json.loads(seed)) if seed else 0,
            'original_mappings': sum(len(p.get('original_image_map', {})) for p in data['products']),
            'deferred_originals': sum(len(p.get('deferred_originals', [])) for p in data['products']),
            'cn_packaging_candidates': len(CN_PACKAGING),
            'version': hashlib.sha256(body + seed + (CN_FILE.read_bytes() if CN_FILE.exists() else b'')).hexdigest()}}


@router.get('/progress')
def progress(request: Request):
    job = getattr(request.app.state, 'tomica_backfill', None)
    return job.snapshot() if job else {'status': 'not_started'}


@router.get('/years')
def year_progress(request: Request):
    from pathlib import Path
    from .config import ROOT
    directory = Path(request.app.state.settings.artifact_dir)
    directory = directory if directory.is_absolute() else ROOT / directory
    path = directory / 'tomica-mall-backfill/release-years.json'
    if not path.exists():
        return {'status': 'not_started'}
    result = json.loads(path.read_text(encoding='utf-8'))
    return {key: value for key, value in result.items() if key not in {'changes', 'conflicts'}} | {
        'conflicts': len(result.get('conflicts', []))}
