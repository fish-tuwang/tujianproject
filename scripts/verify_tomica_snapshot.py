"""Measure a real cold list snapshot and repeat-cache response without data edits."""
import json
from pathlib import Path
import time

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.cache import CatalogCache
from backend.app.config import Settings
from backend.app.repository import CatalogRepository
from backend.app.schemas import TomicaQuery


def main():
    settings = Settings()
    engine = create_engine(settings.database_url)
    cache = CatalogCache(settings.redis_url.get_secret_value(), settings.cache_namespace)
    try:
        assert cache.client is not None and cache.client.ping()
        with Session(engine) as session:
            revision = CatalogRepository(session).get_revision('tomica')
        query = TomicaQuery(q='面包小偷', page=1, limit=21)
        # Clear only these two project metadata keys, never image bytes or other apps.
        api_key = f'api:tomica:{revision}:list-v4:' + cache.signature(query.model_dump())
        cache.client.delete(cache.key(f'rows:tomica:{revision}'), cache.key(api_key))
        results, bodies = [], []
        with httpx.Client(timeout=90, headers={'X-Catalog-Service': settings.auth_service_token.get_secret_value()}) as client:
            for label in ['cold', 'warm']:
                start = time.perf_counter()
                response = client.get('http://127.0.0.1:8092/api/tomica', params={'q': query.q, 'page': 1, 'limit': 21})
                response.raise_for_status()
                bodies.append(response.json())
                results.append({'phase': label, 'ms': round((time.perf_counter() - start) * 1000, 2), 'cache': response.headers.get('x-catalog-cache'), 'http_status': response.status_code})
        assert results[0]['cache'] == 'miss' and results[1]['cache'] == 'hit'
        assert bodies[0] == bodies[1] and bodies[0]['total'] >= 1
        report = {'status': 'pass', 'scope': 'server-local real PostgreSQL/Redis/HTTP', 'metrics': results, 'matches': bodies[0]['total'], 'source_revision': revision}
        (Path(settings.artifact_dir) / 'tomica-snapshot-cache.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report))
    finally:
        engine.dispose()
        cache.close()


if __name__ == '__main__':
    main()
