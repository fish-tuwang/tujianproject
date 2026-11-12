"""Loopback-only OneBot HTTP bridge for the existing private catalog API."""
import asyncio
from contextlib import asynccontextmanager, suppress
import hmac
import json
from pathlib import Path
import sqlite3
import time
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import httpx
from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .audit import audit, configure_audit
from .qq_catalog import CatalogReplies, text_reply


class QQSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='QQ_', env_file=None, extra='ignore')
    account: str = ''
    allowed_groups: str = ''
    onebot_token: SecretStr
    catalog_token: SecretStr
    catalog_api: str = 'http://127.0.0.1:8092'
    account_api: str = 'http://127.0.0.1:3002'
    public_base: str = 'https://117.72.11.77'
    state_path: str = '/app/qq-state/bot.sqlite3'
    log_dir: str = '/app/qq-logs'

    @field_validator('account')
    @classmethod
    def account_number(cls, value):
        if value and (not value.isdecimal() or not 5 <= len(value) <= 12):
            raise ValueError('invalid QQ account')
        return value

    @field_validator('onebot_token', 'catalog_token')
    @classmethod
    def required_secret(cls, value):
        if len(value.get_secret_value()) < 32:
            raise ValueError('a secret of at least 32 characters is required')
        return value

    @field_validator('catalog_api', 'account_api')
    @classmethod
    def loopback_api(cls, value):
        url = urlsplit(value)
        if url.scheme != 'http' or url.hostname != '127.0.0.1' or url.username or url.password or url.query or url.fragment or url.path not in {'', '/'}:
            raise ValueError('only loopback HTTP APIs are allowed')
        return value.rstrip('/')

    @field_validator('allowed_groups')
    @classmethod
    def groups(cls, value):
        value = value.strip()
        if value not in {'', '*'} and any(not x.strip().isdecimal() for x in value.split(',')):
            raise ValueError('groups must be comma-separated IDs or *')
        return value


class BotStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('PRAGMA journal_mode=WAL; CREATE TABLE IF NOT EXISTS seen (group_id TEXT,user_id TEXT,message_id TEXT,at REAL,PRIMARY KEY(group_id,message_id)); CREATE TABLE IF NOT EXISTS context (group_id TEXT,user_id TEXT,data TEXT,expires REAL,PRIMARY KEY(group_id,user_id));')
        self.path.chmod(0o600)

    def connect(self):
        return sqlite3.connect(self.path, timeout=5)

    def claim(self, group, user, message, now=None):
        now = time.time() if now is None else now
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM seen WHERE at<?', (now - 86400,))
            db.execute('DELETE FROM context WHERE expires<?', (now,))
            if db.execute('SELECT 1 FROM seen WHERE group_id=? AND user_id=? AND at>?', (group, user, now - 2)).fetchone():
                return False
            return db.execute('INSERT OR IGNORE INTO seen VALUES (?,?,?,?)', (group, user, message, now)).rowcount == 1

    def context(self, group, user):
        with self.connect() as db:
            row = db.execute('SELECT data FROM context WHERE group_id=? AND user_id=? AND expires>?', (group, user, time.time())).fetchone()
        return json.loads(row[0]) if row else None

    def save_context(self, group, user, data):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO context VALUES (?,?,?,?)', (group, user, json.dumps(data, ensure_ascii=False), time.time() + 900))

    def clear_context(self, group, user):
        with self.connect() as db:
            db.execute('DELETE FROM context WHERE group_id=? AND user_id=?', (group, user))


def group_query(event, settings):
    if not settings.account or event.get('post_type') != 'message' or event.get('message_type') != 'group':
        return None
    if str(event.get('self_id')) != settings.account or str(event.get('user_id')) == settings.account or event.get('anonymous'):
        return None
    group, user, message = (str(event.get(key, '')) for key in ['group_id', 'user_id', 'message_id'])
    if not group.isdecimal() or not user.isdecimal() or not message or len(message) > 40:
        return None
    allowed = settings.allowed_groups
    if allowed != '*' and group not in [v.strip() for v in allowed.split(',')]:
        return None
    segments = event.get('message')
    if not isinstance(segments, list) or not any(isinstance(s, dict) and s.get('type') == 'at' and str((s.get('data') or {}).get('qq')) == settings.account for s in segments):
        return None
    text = ''.join(str(s.get('data', {}).get('text', '')) for s in segments if isinstance(s, dict) and s.get('type') == 'text').strip()
    if len(text) > 200:
        return None
    return group, user, message, text


def create_app(settings, *, catalog_transport=None, account_transport=None):
    store = BotStore(settings.state_path)
    queue = asyncio.Queue(maxsize=32)
    status = {'last_received_at': None, 'last_reply_at': None, 'last_error': None}

    @asynccontextmanager
    async def lifespan(app):
        configure_audit(settings.log_dir, channels={'collection'})
        async with httpx.AsyncClient(base_url=settings.catalog_api, headers={'X-Catalog-Service': settings.catalog_token.get_secret_value()}, timeout=30, transport=catalog_transport, follow_redirects=False, trust_env=False) as catalog:
            async with httpx.AsyncClient(base_url=settings.account_api, headers={'Authorization': 'Bearer ' + settings.onebot_token.get_secret_value()}, timeout=30, transport=account_transport, follow_redirects=False, trust_env=False) as account:
                app.state.account_client = account
                replies = CatalogReplies(catalog, store, settings.public_base)

                async def worker():
                    while True:
                        group, user, message, query = await queue.get()
                        try:
                            try:
                                segments = await replies.reply(group, user, query)
                            except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
                                audit('qq_catalog_query_failed', error=type(error).__name__, group_id=group, user_id=user)
                                segments = text_reply('图鉴暂时无法查询，请稍后再试。')
                            payload = {'group_id': int(group), 'message': [{'type': 'reply', 'data': {'id': message}}, *segments]}
                            response = await account.post('/send_group_msg', json=payload)
                            response.raise_for_status()
                            body = response.json()
                            if body.get('status') != 'ok' or body.get('retcode') != 0 or not (body.get('data') or {}).get('message_id'):
                                raise ValueError('QQ did not acknowledge the reply')
                            status.update(last_reply_at=time.time(), last_error=None)
                            audit('qq_catalog_reply_sent', group_id=group, user_id=user, request_message_id=message, reply_message_id=body['data']['message_id'])
                        except (httpx.HTTPError, ValueError, TypeError) as error:
                            status['last_error'] = type(error).__name__
                            audit('qq_catalog_send_failed', group_id=group, user_id=user, error=type(error).__name__)
                        finally:
                            queue.task_done()

                task = asyncio.create_task(worker())
                try:
                    yield
                finally:
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task

    app = FastAPI(title='QQ图鉴查询桥接', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.queue = queue

    @app.get('/health/live')
    async def live():
        return {'status': 'ok', 'account_configured': bool(settings.account), 'groups_enabled': bool(settings.allowed_groups), **status}

    @app.get('/health/ready')
    async def ready():
        try:
            response = await app.state.account_client.post('/get_login_info', json={})
            response.raise_for_status()
            body = response.json()
            online = body.get('status') == 'ok' and str((body.get('data') or {}).get('user_id')) == settings.account and bool(settings.account) and bool(settings.allowed_groups)
        except (httpx.HTTPError, ValueError):
            online = False
        return JSONResponse({'status': 'ready' if online else 'waiting_for_qq_login', **status}, status_code=200 if online else 503)

    @app.post('/onebot/events')
    async def events(request: Request):
        if not request.client or request.client.host not in {'127.0.0.1', '::1'}:
            return JSONResponse({'ok': False}, status_code=403)
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 65536:
                return JSONResponse({'ok': False}, status_code=413)
        expected = 'sha1=' + hmac.new(settings.onebot_token.get_secret_value().encode(), data, 'sha1').hexdigest()
        if not hmac.compare_digest(request.headers.get('x-signature', '').encode(), expected.encode()):
            return JSONResponse({'ok': False}, status_code=403)
        try:
            event = json.loads(data)
            query = group_query(event, settings) if isinstance(event, dict) else None
        except (ValueError, TypeError, AttributeError):
            return JSONResponse({'ok': False}, status_code=400)
        if query is None:
            return {'ok': True, 'accepted': False}
        if queue.full():
            return JSONResponse({'ok': False}, status_code=503)
        group, user, message, text = query
        if not store.claim(group, user, message):
            return {'ok': True, 'accepted': False}
        queue.put_nowait(query)
        status['last_received_at'] = time.time()
        audit('qq_catalog_query_received', group_id=group, user_id=user, message_id=message, query=text[:100])
        return {'ok': True, 'accepted': True}

    return app


def application():
    return create_app(QQSettings())
