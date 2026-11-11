"""Monthly Tomica releases from explicitly supplied article material."""
import hashlib
import re
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .api import get_session, public_cached
from .config import ROOT
from .models import TomicaNews
from .reference_images import image_type
from .repository import CatalogError

MONTH_PATTERN = r'^\d{4}-(0[1-9]|1[0-2])$'
DIGEST_PATTERN = r'^[0-9a-f]{64}$'
NEWS_IMAGES = ROOT / 'backend/preview/news-assets'
router = APIRouter(prefix='/api/tomica-news')


def image_url(digest):
    return '/api/tomica-news/images/' + digest


def month_title(month):
    year, number = month.split('-')
    return f'{year} 年 {int(number)} 月'


def news_index(session):
    months = {}
    for row in session.scalars(select(TomicaNews).order_by(TomicaNews.archive_month.desc(), TomicaNews.slug)):
        products = [{key: product.get(key) for key in ['id', 'name', 'name_zh', 'number']} |
                    {'image_url': image_url(product['cover_digest'])} for product in row.data['products']]
        month = months.setdefault(row.archive_month, {'month': row.archive_month, 'title': month_title(row.archive_month),
                                                       'product_count': 0, 'products': [], 'cover_image_url': products[0]['image_url']})
        month['products'].extend(products)
        month['product_count'] += len(products)
    return {'items': list(months.values())}


def news_month(session, month):
    rows = list(session.scalars(select(TomicaNews).where(TomicaNews.archive_month == month).order_by(TomicaNews.slug)))
    if not rows:
        return None
    articles = []
    for row in rows:
        products = [{**p, 'image_url': image_url(p['cover_digest']),
                     'photos': [{**photo, 'image_url': image_url(photo['digest'])} for photo in p['photos']]}
                    for p in row.data['products']]
        articles.append({'slug': row.slug, 'title': row.title, 'source_name': row.source_name,
                         'source_url': row.source_url, 'origin': row.data['origin'], 'summary': row.data['summary'],
                         'updated_at': row.updated_at, 'products': products})
    return {'month': month, 'title': month_title(month), 'articles': articles}


def read_news_image(digest, directory=NEWS_IMAGES):
    if not re.fullmatch(DIGEST_PATTERN, digest):
        raise ValueError('invalid news image digest')
    target = directory / (digest + '.jpg')
    if not target.is_file():
        raise CatalogError('NOT_FOUND', '新品原图未收录', 404)
    data = target.read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError('news image does not match its digest')
    return data, image_type(data)


@router.get('')
def index(request: Request, session: Session = Depends(get_session)):
    return public_cached(request, session, 'tomica-news', 'index', {}, lambda repo: news_index(repo.session))


@router.get('/images/{digest}')
def original(digest: Annotated[str, Path(pattern=DIGEST_PATTERN)], request: Request):
    cache = request.app.state.cache
    key = 'news-image:' + digest
    data = cache.get(key)
    origin = 'redis'
    if data is None or hashlib.sha256(data).hexdigest() != digest:
        data, _ = read_news_image(digest)
        cache.set(key, data, ttl=86400)
        origin = 'disk'
    headers = {'ETag': '"' + digest + '"', 'Cache-Control': 'public, max-age=86400',
               'X-Content-Type-Options': 'nosniff', 'X-Catalog-Cache': origin}
    if request.headers.get('if-none-match') == headers['ETag']:
        return Response(status_code=304, headers=headers)
    return Response(data, media_type=image_type(data), headers=headers)


@router.get('/{month}')
def monthly(month: Annotated[str, Path(pattern=MONTH_PATTERN)], request: Request, session: Session = Depends(get_session)):
    return public_cached(request, session, 'tomica-news', 'month', month, lambda repo: news_month(repo.session, month), '本月暂未收录新品', ttl=86400)
