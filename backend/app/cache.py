import hashlib
import json
import logging
import threading
import time

from fastapi.encoders import jsonable_encoder
from redis import Redis
from redis.exceptions import RedisError
from redis.backoff import NoBackoff
from redis.retry import Retry

LOG = logging.getLogger('catalog.cache')


class CatalogCache:
    def __init__(self, url='', namespace='dual-catalog:v2', client=None):
        self.client = client or (Redis.from_url(url, socket_connect_timeout=0.2, socket_timeout=0.2, max_connections=16, retry=Retry(NoBackoff(), 0)) if url else None)
        self.namespace = namespace
        self.retry_at = 0
        self.lock = threading.RLock()
        self.snapshots = {}

    def key(self, value):
        return self.namespace + ':' + value

    def get(self, key):
        if self.client is None or time.monotonic() < self.retry_at:
            return None
        try:
            return self.client.get(self.key(key))
        except RedisError as error:
            self.retry_at = time.monotonic() + 5
            LOG.warning('cache unavailable: %s', type(error).__name__)
            return None

    def set(self, key, value, ttl=600):
        if self.client is None or time.monotonic() < self.retry_at:
            return
        try:
            self.client.set(self.key(key), value, ex=ttl)
        except RedisError as error:
            self.retry_at = time.monotonic() + 5
            LOG.warning('cache unavailable: %s', type(error).__name__)

    def get_json(self, key):
        raw = self.get(key)
        if raw is not None:
            try:
                return json.loads(raw)
            except (ValueError, UnicodeError):
                pass
        return None

    def set_json(self, key, value, ttl=600):
        self.set(key, json.dumps(jsonable_encoder(value), ensure_ascii=False, separators=(',', ':')).encode(), ttl)

    def remember(self, key, loader, ttl=600):
        value = self.get_json(key)
        if value is not None:
            return value

        if self.client is None or time.monotonic() < self.retry_at:
            return loader()
        with self.lock:
            value = self.get_json(key)
            if value is None:
                value = loader()
                if value is not None:
                    self.set_json(key, value, ttl)
            return value

    def snapshot(self, source, revision, loader, ttl=600):
        # Keep one decoded snapshot per catalog, never one per search or revision.
        # Redis remains the shared cache; this avoids decoding the entire large
        # catalog independently in each request thread.
        with self.lock:
            previous = self.snapshots.get(source)
            if previous and previous[0] == revision and time.monotonic() < previous[1]:
                return previous[2]
            value = self.remember(f'rows:{source}:{revision}', loader, ttl=ttl)
            self.snapshots[source] = (revision, time.monotonic() + ttl, value)
            return value

    @staticmethod
    def signature(value):
        return hashlib.sha256(json.dumps(jsonable_encoder(value), sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def close(self):
        if self.client is not None:
            self.client.close()
