"""Real Redis and public HTTP cache acceptance; no catalog writes."""
import json
from pathlib import Path
import statistics
import time
from uuid import uuid4
import httpx
from backend.app.config import Settings
from backend.app.cache import CatalogCache


def main():
    settings = Settings()
    cache = CatalogCache(settings.redis_url.get_secret_value(), settings.cache_namespace)
    checks = []
    def check(name, value):
        if not value:
            raise AssertionError(name)
        checks.append(name)
    client = cache.client
    check('real Redis responds', client is not None and client.ping())
    key = 'verify:' + uuid4().hex
    try:
        cache.set(key, b'actual redis roundtrip', ttl=2)
        check('real bytes roundtrip', cache.get(key) == b'actual redis roundtrip')
        check('real expiry configured', 0 < client.ttl(cache.key(key)) <= 2)
        time.sleep(2.1)
        check('real expiry applied', cache.get(key) is None)
    finally:
        client.delete(cache.key(key))
    metrics = []
    base = 'http://127.0.0.1:8092'
    with httpx.Client(timeout=60, headers={'X-Catalog-Service': settings.auth_service_token.get_secret_value()}) as http:
        payload = http.get(base + '/api/pokemon/1').json()
        endpoints = ['/api/tomica?limit=20&page=1', '/api/tomica?limit=20&page=2', '/api/pokemon?limit=12', '/api/pokemon/1', '/api/tomica/filters', payload['preview_image_url']]
        for endpoint in endpoints:
            responses = []
            elapsed = []
            for _ in range(3):
                start = time.perf_counter()
                response = http.get(base + endpoint)
                elapsed.append(round((time.perf_counter() - start) * 1000, 2))
                response.raise_for_status()
                responses.append(response)
            check(endpoint + ' cache hit', responses[-1].headers.get('x-catalog-cache') in {'hit', 'redis'})
            check(endpoint + ' content unchanged', responses[0].content == responses[-1].content)
            metrics.append({'url': endpoint, 'ms': elapsed, 'warm_median_ms': statistics.median(elapsed[1:]), 'cache': responses[-1].headers.get('x-catalog-cache')})
        one = http.get(base + endpoints[0]).json()
        two = http.get(base + endpoints[1]).json()
        check('twenty cars per full page', len(one['items']) == len(two['items']) == 20)
        check('pages do not overlap', not ({i['id'] for i in one['items']} & {i['id'] for i in two['items']}))
    offline = CatalogCache('redis://127.0.0.1:1/0')
    try:
        check('real unavailable connection falls back', offline.remember('probe', lambda: 'fallback') == 'fallback')
    finally:
        offline.close()
    memory = client.info('memory')
    keys = list(client.scan_iter(match=cache.namespace + ':*'))
    report = {'status': 'pass', 'assertions': len(checks), 'checks': checks, 'metrics': metrics, 'redis_used_memory': memory['used_memory'], 'redis_maxmemory': memory['maxmemory'], 'cache_keys': len(keys)}
    output = Path(settings.artifact_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / 'redis-cache-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=True))
    cache.close()


if __name__ == '__main__':
    main()
