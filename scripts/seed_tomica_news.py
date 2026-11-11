"""Validate and import supplied monthly releases, without accessing article sites."""
import argparse
import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.cache import CatalogCache
from backend.app.config import ROOT, Settings
from backend.app.models import TomicaNews, now
from backend.app.news import DIGEST_PATTERN, MONTH_PATTERN, NEWS_IMAGES, read_news_image
from backend.app.repository import CatalogError, CatalogRepository


class InputRecord(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class Photo(InputRecord):
    digest: str = Field(pattern=DIGEST_PATTERN)
    caption: str = Field(min_length=1)


class Product(InputRecord):
    id: str = Field(pattern=r'^[a-z0-9][a-z0-9-]*$')
    name: str = Field(min_length=1)
    name_zh: str = ''
    number: str | None = None
    cover_digest: str = Field(pattern=DIGEST_PATTERN)
    summary: str = Field(min_length=1)
    observations: list[str]
    photos: list[Photo] = Field(min_length=1)

    @model_validator(mode='after')
    def cover_belongs_to_product(self):
        if self.cover_digest not in {p.digest for p in self.photos}:
            raise ValueError('cover must belong to the product gallery')
        return self


class Content(InputRecord):
    origin: Literal['user-upload']
    summary: str = Field(min_length=1)
    products: list[Product] = Field(min_length=1)

    @model_validator(mode='after')
    def unique_products_and_images(self):
        ids = [p.id for p in self.products]
        images = [photo.digest for p in self.products for photo in p.photos]
        if len(ids) != len(set(ids)) or len(images) != len(set(images)):
            raise ValueError('products and their photos must not overlap')
        return self


class Article(InputRecord):
    slug: str = Field(pattern=r'^[a-z0-9][a-z0-9-]*$')
    archive_month: str = Field(pattern=MONTH_PATTERN)
    title: str = Field(min_length=1)
    source_name: str = Field(min_length=1)
    source_url: HttpUrl
    data: Content


def load_articles(directory, image_directory=NEWS_IMAGES):
    articles = []
    for path in sorted(Path(directory).glob('*.json')):
        article = Article.model_validate_json(path.read_text(encoding='utf-8')).model_dump(mode='json')
        for product in article['data']['products']:
            for photo in product['photos']:
                try:
                    read_news_image(photo['digest'], image_directory)
                except CatalogError as exc:
                    raise ValueError('missing original news image') from exc
        articles.append(article)
    if len({a['slug'] for a in articles}) != len(articles):
        raise ValueError('duplicate article slug')
    return articles


def import_articles(session, articles, changes=None):
    stats = {'created': 0, 'updated': 0, 'unchanged': 0}
    for article in articles:
        digest = hashlib.sha256(json.dumps(article, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
        row = session.scalar(select(TomicaNews).where(TomicaNews.slug == article['slug']))
        if row is not None and row.content_hash == digest:
            stats['unchanged'] += 1
            continue
        if row is None:
            row = TomicaNews(**article, content_hash=digest)
            session.add(row)
            stats['created'] += 1
            action = 'created'
        else:
            for key, value in article.items():
                setattr(row, key, value)
            row.content_hash = digest
            row.checked_at = row.updated_at = now()
            stats['updated'] += 1
            action = 'updated'
        if changes is not None:
            changes.append({'action': action, 'slug': article['slug'], 'month': article['archive_month'], 'name': article['title'], 'source_url': article['source_url']})
    if stats['created'] or stats['updated']:
        CatalogRepository(session).bump_revision('tomica-news')
    return stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=ROOT / 'backend/data/tomica-news')
    args = parser.parse_args()
    articles = load_articles(args.directory)
    settings = Settings()
    from backend.app.audit import audit, configure_audit
    configure_audit(Path(settings.artifact_dir).parent / 'logs', channels={'collection'})
    engine = create_engine(settings.database_url)
    cache = CatalogCache(settings.redis_url.get_secret_value(), settings.cache_namespace)
    try:
        changes = []
        with Session(engine) as session, session.begin():
            stats = import_articles(session, articles, changes=changes)
        for change in changes:
            audit('news_' + change['action'], source='tomica-news', ingestion='local_import', **change)
        audit('news_import_finished', source='tomica-news', ingestion='local_import', counts=stats)
        images = {p['digest'] for a in articles for item in a['data']['products'] for p in item['photos']}
        warmed = 0
        for digest in images:
            data, _ = read_news_image(digest)
            cache.set('news-image:' + digest, data, ttl=86400)
            warmed += cache.get('news-image:' + digest) == data
        print(json.dumps({**stats, 'photos_ready': len(images), 'redis_warmed': warmed}), flush=True)
    finally:
        engine.dispose()
        cache.close()


if __name__ == '__main__':
    main()
