"""Loopback-only OneBot bridge for Qwen group chat."""
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
from pydantic import SecretStr, field_validator, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .audit import audit, configure_audit
from .qq_chat import ChatReplies
from .qq_images import ChatImages
from .engagement import EngagementStore, activity_target, batches, segment_key


class QQSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='QQ_', env_file=None, extra='ignore')
    account: str = ''
    allowed_groups: str = ''
    onebot_token: SecretStr
    llm_key: SecretStr
    llm_base: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    llm_model: str = "qwen-plus"
    account_api: str = 'http://127.0.0.1:3002'
    state_path: str = '/app/qq-state/bot.sqlite3'
    log_dir: str = '/app/qq-logs'
    idle_enabled: bool = False
    idle_minutes: int = Field(default=30, ge=15, le=1440)
    idle_daily_limit: int = Field(default=3, ge=1, le=3)

    @field_validator('account')
    @classmethod
    def account_number(cls, value):
        if value and (not value.isdecimal() or not 5 <= len(value) <= 12):
            raise ValueError('invalid QQ account')
        return value

    @field_validator('onebot_token', 'llm_key')
    @classmethod
    def required_secret(cls, value):
        if len(value.get_secret_value()) < 32:
            raise ValueError('a secret of at least 32 characters is required')
        return value

    @field_validator('account_api')
    @classmethod
    def loopback_api(cls, value):
        url = urlsplit(value)
        if url.scheme != 'http' or url.hostname != '127.0.0.1' or url.username or url.password or url.query or url.fragment or url.path not in {'', '/'}:
            raise ValueError('only loopback HTTP APIs are allowed')
        return value.rstrip('/')

    @field_validator('llm_base')
    @classmethod
    def model_endpoint(cls, value):
        url = urlsplit(value)
        if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError('model endpoint requires HTTPS without credentials')
        return value.rstrip('/')

    @field_validator('allowed_groups')
    @classmethod
    def groups(cls, value):
        value = value.strip()
        if value not in {'', '*'} and any(not x.strip().isdecimal() for x in value.split(',')):
            raise ValueError('groups must be comma-separated IDs or *')
        return value


class BotStore(EngagementStore):
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('PRAGMA journal_mode=WAL; CREATE TABLE IF NOT EXISTS seen (group_id TEXT,user_id TEXT,message_id TEXT,at REAL,PRIMARY KEY(group_id,message_id)); CREATE TABLE IF NOT EXISTS pending (group_id TEXT,user_id TEXT,message_id TEXT,text TEXT,at REAL,PRIMARY KEY(group_id,message_id)); CREATE TABLE IF NOT EXISTS context (group_id TEXT,user_id TEXT,data TEXT,expires REAL,PRIMARY KEY(group_id,user_id));')
        self.setup_engagement()
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

    def remember(self, group, user, message, text):
        now = time.time()
        with self.connect() as db:
            db.execute('DELETE FROM pending WHERE at<?', (now - 120,))
            db.execute('INSERT OR IGNORE INTO pending VALUES (?,?,?,?,?)', (group, user, message, text, now))
            db.execute('DELETE FROM pending WHERE group_id=? AND user_id=? AND message_id NOT IN (SELECT message_id FROM pending WHERE group_id=? AND user_id=? ORDER BY at DESC LIMIT 5)', (group, user, group, user))

    def take_pending(self, group, user):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            rows = db.execute('SELECT text FROM pending WHERE group_id=? AND user_id=? AND at>? ORDER BY at', (group, user, time.time() - 120)).fetchall()
            db.execute('DELETE FROM pending WHERE group_id=? AND user_id=?', (group, user))
        return [row[0] for row in rows]

    def clear_context(self, group, user):
        with self.connect() as db:
            db.execute('DELETE FROM context WHERE group_id=? AND user_id=?', (group, user))


def group_query(event, settings, *, require_at=True):
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
    if not isinstance(segments, list):
        return None
    if require_at and not any(isinstance(s, dict) and s.get('type') == 'at' and str((s.get('data') or {}).get('qq')) == settings.account for s in segments):
        return None
    text = ''.join(str(s.get('data', {}).get('text', '')) for s in segments if isinstance(s, dict) and s.get('type') == 'text').strip()
    if len(text) > 200:
        return None
    return group, user, message, text


def create_app(settings, *, llm_transport=None, account_transport=None):
    store = BotStore(settings.state_path)
    queue = asyncio.Queue(maxsize=32)
    status = {'last_received_at': None, 'last_reply_at': None, 'last_error': None}

    @asynccontextmanager
    async def lifespan(app):
        configure_audit(settings.log_dir, channels={'collection'})
        async with httpx.AsyncClient(base_url=settings.llm_base.rstrip('/') + '/', headers={'Authorization': 'Bearer ' + settings.llm_key.get_secret_value()}, timeout=45, transport=llm_transport, follow_redirects=False, trust_env=False) as llm, httpx.AsyncClient(base_url='https://dashscope.aliyuncs.com', headers={'Authorization': 'Bearer ' + settings.llm_key.get_secret_value()}, timeout=20, follow_redirects=False, trust_env=False) as image_api, httpx.AsyncClient(timeout=20, follow_redirects=False, trust_env=False) as downloads:
            async with httpx.AsyncClient(base_url=settings.account_api, headers={'Authorization': 'Bearer ' + settings.onebot_token.get_secret_value()}, timeout=30, transport=account_transport, follow_redirects=False, trust_env=False) as account:
                app.state.account_client = account
                replies = ChatReplies(llm, store, settings.llm_model, ChatImages(image_api, downloads))

                async def worker():
                    while True:
                        group, user, message, query = await queue.get()
                        try:
                            idle=user=='__idle__'
                            if idle and not store.idle_allowed(group,minutes=settings.idle_minutes,limit=settings.idle_daily_limit):continue
                            try:
                                segments = await replies.reply(group, user, query,idle=idle)
                            except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as error:
                                audit('qq_chat_query_failed', error=type(error).__name__, group_id=group, user_id=user)
                                raise ValueError('model generation failed') from error
                            if idle and not store.idle_allowed(group,minutes=settings.idle_minutes,limit=settings.idle_daily_limit):continue
                            outbound=batches(segments,message)
                            idle_recorded=False
                            for batch in outbound:
                                payload = {'group_id': int(group), 'message': batch}
                                response = await account.post('/send_group_msg', json=payload)
                                response.raise_for_status()
                                body = response.json()
                                if body.get('status') != 'ok' or body.get('retcode') != 0 or not (body.get('data') or {}).get('message_id'):
                                    raise ValueError('QQ did not acknowledge the reply')
                                if idle and not idle_recorded:
                                    store.record_idle(group,' '.join(r.get('data',{}).get('text','') for r in segments));idle_recorded=True
                                for segment in batch:
                                    if segment.get('type')=='image':store.record_image(group,segment_key(segment))
                                status.update(last_reply_at=time.time(), last_error=None)
                                audit('qq_chat_reply_sent', group_id=group, user_id=user, request_message_id=message, reply_message_id=body['data']['message_id'], content_type='image' if batch[0]['type'] == 'image' else 'text')
                        except (httpx.HTTPError, ValueError, TypeError) as error:
                            status['last_error'] = type(error).__name__
                            audit('qq_chat_send_failed', group_id=group, user_id=user, error=type(error).__name__)
                        finally:
                            queue.task_done()

                async def idle_loop():
                    while True:
                        await asyncio.sleep(60)
                        if not settings.idle_enabled or queue.full():continue
                        try:
                            info=(await account.post('/get_login_info',json={})).json()
                            if info.get('status')!='ok' or str((info.get('data') or {}).get('user_id'))!=settings.account:continue
                            for group in store.idle_candidates(minutes=settings.idle_minutes,limit=settings.idle_daily_limit):
                                if queue.full():break
                                if settings.allowed_groups!='*' and group not in [v.strip() for v in settings.allowed_groups.split(',')]:continue
                                if store.claim_idle(group,minutes=settings.idle_minutes,limit=settings.idle_daily_limit):queue.put_nowait((group,'__idle__','','现在群里很安静，允许自然地冒泡一次。'))
                        except (httpx.HTTPError,ValueError,sqlite3.Error) as error:
                            audit('qq_idle_check_failed',error=type(error).__name__)

                task = asyncio.create_task(worker())
                idle_task = asyncio.create_task(idle_loop())
                try:
                    yield
                finally:
                    task.cancel();idle_task.cancel()
                    with suppress(asyncio.CancelledError):await task
                    with suppress(asyncio.CancelledError):await idle_task

    app = FastAPI(title='QQ千问聊天桥接', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.queue = queue

    @app.get('/health/live')
    async def live():
        return {'status': 'ok', 'account_configured': bool(settings.account), 'groups_enabled': bool(settings.allowed_groups), 'idle_enabled':settings.idle_enabled, **status}

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
            activity=activity_target(event,settings)
            if activity:store.note_activity(*activity)
            query = group_query(event, settings) if isinstance(event, dict) else None
        except (ValueError, TypeError, AttributeError):
            return JSONResponse({'ok': False}, status_code=400)
        if query is None:
            passive = group_query(event, settings, require_at=False) if isinstance(event, dict) else None
            if passive and passive[3] and not any(isinstance(s, dict) and s.get('type') == 'at' for s in event.get('message', [])):
                store.remember(*passive)
            return {'ok': True, 'accepted': False}
        if queue.full():
            return JSONResponse({'ok': False}, status_code=503)
        group, user, message, text = query
        if not store.claim(group, user, message):
            return {'ok': True, 'accepted': False}
        pending = store.take_pending(group, user)
        if pending:
            text = '我刚才连续说的话：\n' + '\n'.join(pending) + '\n这条@消息：' + (text or '请接着回答我刚才的问题。')
        queue.put_nowait((group, user, message, text))
        status['last_received_at'] = time.time()
        audit('qq_chat_query_received', group_id=group, user_id=user, message_id=message, query_length=len(text))
        return {'ok': True, 'accepted': True}

    return app


def application():
    return create_app(QQSettings())
