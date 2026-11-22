"""Authenticated local administration; no credentials or conversation bodies leave this API."""
import json
from pathlib import Path

from fastapi.responses import JSONResponse


def preferences(store):
    with store.connect() as db:
        db.execute('CREATE TABLE IF NOT EXISTS panel_settings (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL)')
        row = db.execute('SELECT data FROM panel_settings WHERE id=1').fetchone()
    return json.loads(row[0]) if row else {}


def save_preferences(store, data):
    if set(data) - {'idle_enabled', 'idle_minutes', 'idle_daily_limit', 'persona_note'}:
        raise ValueError('unsupported setting')
    if 'idle_enabled' in data and type(data['idle_enabled']) is not bool:
        raise ValueError('idle_enabled must be boolean')
    for key, low, high in [('idle_minutes', 30, 1440), ('idle_daily_limit', 0, 3)]:
        if key in data and (type(data[key]) is not int or not low <= data[key] <= high):
            raise ValueError('setting outside allowed range')
    if 'persona_note' in data and (not isinstance(data['persona_note'], str) or len(data['persona_note']) > 3000):
        raise ValueError('persona note too long')
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('CREATE TABLE IF NOT EXISTS panel_settings (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL)')
        row = db.execute('SELECT data FROM panel_settings WHERE id=1').fetchone()
        merged = {**(json.loads(row[0]) if row else {}), **data}
        db.execute('INSERT OR REPLACE INTO panel_settings VALUES(1,?)', (json.dumps(merged, ensure_ascii=False),))
    return merged


def install_panel_api(app, settings, store, status):
    import hmac
    from fastapi import Request
    from .qq_chat import PERSONALITY

    @app.post('/admin/panel')
    async def panel(request: Request):
        if not request.client or request.client.host not in {'127.0.0.1', '::1'} or not hmac.compare_digest(
            request.headers.get('authorization', ''), 'Bearer ' + settings.onebot_token.get_secret_value()
        ):
            return JSONResponse({'ok': False}, status_code=403)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 16384:
                return JSONResponse({'ok': False}, status_code=413)
        try:
            data = json.loads(body)
            action = data.get('action')
            if action == 'save':
                values = save_preferences(store, data.get('values', {}))
                for name in ('idle_enabled', 'idle_minutes', 'idle_daily_limit'):
                    if name in values:
                        setattr(settings, name, values[name])
                return {'ok': True}
            if action == 'status':
                response = await app.state.account_client.post('/get_login_info', json={})
                account = response.json()
                online = account.get('status') == 'ok' and str((account.get('data') or {}).get('user_id')) == settings.account
                with store.connect() as db:
                    groups = [{'group': r[0], 'last_human': r[1], 'idle_count': r[2], 'date': r[3]} for r in db.execute('SELECT group_id,last_human,idle_count,count_date FROM group_activity ORDER BY last_human DESC LIMIT 100')]
                index = json.loads((Path(__file__).parent / 'qq_stickers/index.json').read_text())
                return {'ok': True, 'online': online, 'account': settings.account, 'model': settings.llm_model,
                        'allowed_groups': settings.allowed_groups, 'groups': groups, 'status': status,
                        'settings': {'idle_enabled': settings.idle_enabled, 'idle_minutes': settings.idle_minutes,
                                     'idle_daily_limit': settings.idle_daily_limit, **preferences(store)},
                        'personality': PERSONALITY, 'stickers': index['entries']}
            raise ValueError('unsupported action')
        except (ValueError, TypeError, AttributeError):
            return JSONResponse({'ok': False, 'error': 'invalid request'}, status_code=400)
