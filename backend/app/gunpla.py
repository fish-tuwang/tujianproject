"""Private Gunpla catalog, isolated from the two existing catalog projections."""
from copy import deepcopy
from datetime import datetime
from functools import lru_cache
import hashlib
import json
import re
from typing import Annotated, Literal
import unicodedata
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .api import get_session, public_cached
from .config import ROOT
from .models import GunplaEntry, ImageAsset, now
from .repository import CatalogError, CatalogRepository
from .sources.gunpla import EXCLUDED_BRANDS, SALE_TYPES, image_url, is_model_product

router = APIRouter(prefix='/api/gunpla')


def normalized(value):
    return re.sub(r'[\W_]+', '', unicodedata.normalize('NFKC', value).casefold())


def preview(asset_id):
    return '/api/reference-images/' + asset_id if asset_id else None


@lru_cache(maxsize=1)
def series_years():
    return json.loads((ROOT / 'backend/data/gunpla-series-years.json').read_text(encoding='utf-8'))


def series_groups(rows):
    grouped = {}
    for row in rows:
        year = series_years().get(row.source_key, {}).get('year')
        key = str(year // 10 * 10) if year else 'other'
        grouped.setdefault(key, []).append({'id': row.source_key, 'name': row.name, 'year': year, 'preview_image_url': preview(row.data.get('logo_image_id'))})
    return [{'id': key, 'name': key + '年代' if key != 'other' else '其他企划 / 年代未确认', 'items': sorted(grouped[key], key=lambda r: (r['year'] or 9999, int(r['id'])))} for key in sorted(grouped)]


def register_image(session, url):
    if not url:
        return None
    url = image_url(url)
    row = session.scalar(select(ImageAsset).where(ImageAsset.source_url == url))
    if row is None:
        row = ImageAsset(id=str(uuid5(NAMESPACE_URL, url)), source_url=url, attribution='BANDAI SPIRITS')
        session.add(row)
        session.flush()
    return row.id


def import_catalog(session, document, changes=None):
    if document.get('schema_version') != 1 or not isinstance(document.get('entries'), list):
        raise ValueError('unsupported Gunpla export')
    report = {'created': 0, 'updated': 0, 'unchanged': 0, 'failed': 0, 'import_errors': []}
    accepted = {'product', 'brand', 'series', 'event', 'announcement'}
    series = {r.source_key for r in session.scalars(select(GunplaEntry).where(GunplaEntry.kind == 'series'))}
    series.update(str(r['source_key']) for r in document['entries'] if r.get('kind') == 'series')
    seen = {}
    for position, entry in enumerate(document['entries']):
        if not isinstance(entry, dict):
            report['failed'] += 1
            report['import_errors'].append({'error': 'invalid entry object'})
            continue
        kind, key = entry.get('kind'), str(entry.get('source_key', ''))
        try:
            name, data = entry['name'], deepcopy(entry['data'])
            if kind not in accepted or not key or len(key) > 120 or not isinstance(name, str) or not name.strip() or not isinstance(data, dict):
                raise ValueError('invalid entry')
            if kind in {'brand', 'series'}:
                data['order'] = position
            semantic = json.dumps({'kind': kind, 'key': key, 'name': name, 'data': data}, sort_keys=True, ensure_ascii=False)
            digest = hashlib.sha256(semantic.encode()).hexdigest()
            identity = (kind, key)
            if identity in seen:
                if seen[identity] != digest:
                    raise ValueError('conflicting duplicate entry')
                continue
            seen[identity] = digest
            if kind == 'brand' and key in EXCLUDED_BRANDS:
                raise ValueError('accessory brand')
            if kind == 'product':
                if not all(isinstance(data.get(field), list) and all(isinstance(value, str) and re.fullmatch(r'[1-9][0-9]*', value) for value in data[field]) for field in ['brand_ids', 'series_ids', 'sale_types']):
                    raise ValueError('invalid product classification arrays')
                if not re.fullmatch(r'[1-9][0-9]*', key) or str(data.get('official_id')) != key or not is_model_product(entry, series)[0]:
                    raise ValueError('entry is not a model product')
                if not data.get('sale_types') or set(data['sale_types']) - set(SALE_TYPES) or not data.get('brand_ids'):
                    raise ValueError('unverified product classification')
                if not isinstance(data.get('gallery_urls'), list) or not 1 <= len(data['gallery_urls']) <= 200:
                    raise ValueError('invalid product gallery')
            with session.begin_nested():
                row = session.scalar(select(GunplaEntry).where(GunplaEntry.kind == kind, GunplaEntry.source_key == key))
                if row is not None and row.content_hash == digest:
                    report['unchanged'] += 1
                    continue
                for source, target in [('cover_url', 'cover_image_id'), ('logo_url', 'logo_image_id')]:
                    if data.get(source):
                        data[target] = register_image(session, data[source])
                if kind == 'product':
                    for source, target in [('gallery_urls', 'gallery_image_ids'), ('detail_image_urls', 'detail_image_ids')]:
                        data[target] = list(dict.fromkeys(register_image(session, url) for url in data.get(source, [])))
                action = 'created' if row is None else 'updated'
                if row is None:
                    row = GunplaEntry(kind=kind, source_key=key, name=name, data=data, content_hash=digest)
                    session.add(row)
                else:
                    row.name, row.data, row.content_hash, row.updated_at = name, data, digest, now()
                session.flush()
            report[action] += 1
            if changes is not None:
                changes.append({'action': action, 'kind': 'gunpla_' + kind, 'entity_id': key, 'name': name})
        except (KeyError, TypeError, ValueError, SQLAlchemyError) as error:
            report['failed'] += 1
            report['import_errors'].append({'kind': kind, 'key': key, 'error': str(error)[:120]})
    if report['created'] or report['updated']:
        CatalogRepository(session).bump_revision('gunpla')
    return report


class GunplaQuery(BaseModel):
    mode: Literal['grade', 'series'] = 'grade'
    grade: str = Field(default='', pattern=r'^(?:[1-9][0-9]*)?$')
    series: str = Field(default='', pattern=r'^(?:[1-9][0-9]*)?$')
    sale_type: Literal['', '1', '2', '3', '4'] = ''
    scale: str = Field(default='', pattern=r'^(?:1/[1-9][0-9]{0,3}|unscaled)?$')
    q: str = Field(default='', max_length=100)
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=20, ge=1, le=100)

    @field_validator('limit')
    @classmethod
    def supported_limit(cls, value):
        if value not in {20, 40, 60, 100}:
            raise ValueError('unsupported page size')
        return value


class GunplaRepository:
    def __init__(self, session, cache=None):
        self.session, self.cache = session, cache

    def summary_rows(self):
        def load():
            rows = []
            for row in self.session.scalars(select(GunplaEntry).where(GunplaEntry.kind == 'product')):
                data = row.data
                fields = ['brand_ids', 'series_ids', 'sale_types', 'scale', 'release_text', 'release_sort', 'release_precision', 'price_cny_text', 'price_jpy_text']
                rows.append({'id': row.source_key, 'name': row.name, **{key: data.get(key) for key in fields}, 'preview_image_url': preview(data.get('cover_image_id'))})
            return rows
        revision = CatalogRepository(self.session).get_revision('gunpla')
        return self.cache.snapshot('gunpla', revision, load, ttl=600) if self.cache else load()

    def filters(self):
        records = list(self.session.scalars(select(GunplaEntry).where(GunplaEntry.kind.in_(['brand', 'series'])).order_by(GunplaEntry.source_key)))
        records.sort(key=lambda r: (r.data.get('order', 9999), r.source_key))
        brands = [{'id': r.source_key, 'name': r.name, 'preview_image_url': preview(r.data.get('logo_image_id'))} for r in records if r.kind == 'brand']
        return {'brands': brands, 'scales': sorted({r['scale'] for r in self.summary_rows() if r['scale']}), 'sale_types': [{'id': key, 'name': name} for key, name in SALE_TYPES.items()], 'series_groups': series_groups([r for r in records if r.kind == 'series'])}

    def list_products(self, query):
        rows = self.summary_rows()
        if query.mode == 'series':
            rows = [r for r in rows if not query.series or query.series in r['series_ids']]
        else:
            rows = [r for r in rows if (not query.grade or query.grade in r['brand_ids']) and (not query.sale_type or query.sale_type in r['sale_types'])]
        if query.scale:
            rows = [r for r in rows if (r['scale'] or 'unscaled') == query.scale]
        if query.q:
            term = normalized(query.q)
            rows = [r for r in rows if term in normalized(r['name'] + ' ' + r['id'])]
        rows = sorted(rows, key=lambda r: (r['release_sort'] or '', int(r['id'])), reverse=True)
        total, pages = len(rows), max(1, (len(rows) + query.limit - 1) // query.limit)
        page = min(query.page, pages)
        return {'items': rows[(page - 1) * query.limit:page * query.limit], 'total': total, 'page': page, 'page_size': query.limit, 'total_pages': pages, 'next_cursor': None}

    def product(self, official_id):
        row = self.session.scalar(select(GunplaEntry).where(GunplaEntry.kind == 'product', GunplaEntry.source_key == str(official_id)))
        if row is None:
            return None
        data = row.data
        return {'id': row.source_key, 'name': row.name, 'price_cny_text': data.get('price_cny_text'), 'price_jpy_text': data.get('price_jpy_text'), 'release_text': data.get('release_text'), 'cover': preview(data.get('cover_image_id')), 'gallery': list(dict.fromkeys(preview(key) for key in data.get('gallery_image_ids', []))), 'detail_images': list(dict.fromkeys(preview(key) for key in data.get('detail_image_ids', [])))}

    def home(self, today=None):
        today = today or datetime.now(ZoneInfo('Asia/Shanghai')).date()
        records = list(self.session.scalars(select(GunplaEntry).where(GunplaEntry.kind.in_(['event', 'announcement']))))
        events = [{'id': r.source_key, 'name': r.name, 'preview_image_url': preview(r.data.get('cover_image_id')), **{key: r.data.get(key) for key in ['channel', 'status_text', 'date_text']}} for r in records if r.kind == 'event']
        events.sort(key=lambda r: r['date_text'] or '', reverse=True)
        upcoming = {}
        for item in sorted(self.summary_rows(), key=lambda r: (r['release_sort'] or '9999', -int(r['id']))):
            release = item.get('release_sort') or ''
            if release[:7] >= today.isoformat()[:7] and release:
                if item.get('release_precision') == 'day' and release < today.isoformat():
                    continue
                upcoming.setdefault(release[:7], []).append(item)
        return {'events': events, 'upcoming': [{'month': key, 'items': value[:12], 'total': len(value)} for key, value in upcoming.items()], 'announcements': [{'id': r.source_key, 'name': r.name, 'date_text': r.data.get('date_text')} for r in records if r.kind == 'announcement']}


def cached(request, session, view, params, loader, ttl=600):
    return public_cached(request, session, 'gunpla', view, params, lambda repo: loader(GunplaRepository(repo.session, repo.cache)), '模型尚未收录', ttl)


@router.get('')
def listing(request: Request, query: Annotated[GunplaQuery, Query()], session: Session = Depends(get_session)):
    if query.mode == 'series':
        query.grade, query.sale_type = '', ''
    return cached(request, session, 'list', query.model_dump(), lambda repo: repo.list_products(query))


@router.get('/filters')
def filters(request: Request, session: Session = Depends(get_session)):
    return cached(request, session, 'filters', {}, lambda repo: repo.filters())


@router.get('/home')
def home(request: Request, session: Session = Depends(get_session)):
    today = datetime.now(ZoneInfo('Asia/Shanghai')).date()
    return cached(request, session, 'home', str(today), lambda repo: repo.home(today))


@router.get('/products/{official_id}')
def detail(official_id: int, request: Request, session: Session = Depends(get_session)):
    return cached(request, session, 'product', official_id, lambda repo: repo.product(official_id), ttl=86400)
