"""Keep the existing authenticated OneBot transport while running FatFish on macOS."""
import asyncio
import hmac
import json
import time

from fastapi import Request
from fastapi.responses import JSONResponse


def install_gateway(app, settings, store, status):
    events = asyncio.Queue(maxsize=1000)
    app.state.fatfish_events = events
    app.state.fatfish_poll_at = 0

    @app.post('/admin/fatfish')
    async def gateway(request: Request):
        if not request.client or request.client.host not in {'127.0.0.1', '::1'} or not hmac.compare_digest(
            request.headers.get('authorization', ''), 'Bearer ' + settings.onebot_token.get_secret_value()
        ):
            return JSONResponse({'ok': False}, status_code=403)
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 24 * 1024 * 1024:
                return JSONResponse({'ok': False}, status_code=413)
        try:
            data = json.loads(raw)
            operation = data.get('operation')
            if operation == 'poll':
                app.state.fatfish_poll_at = time.time()
                try:
                    event = await asyncio.wait_for(events.get(), 20)
                    return {'event': event}
                except asyncio.TimeoutError:
                    return {'event': None}
            if operation == 'idle_candidates':
                return {'groups': store.idle_candidates(minutes=settings.idle_minutes, limit=settings.idle_daily_limit) if settings.idle_enabled else []}
            if operation == 'idle_check':
                group = str(data.get('group'))
                activity = store.activity(group)
                continuing = data.get('continuing') and activity and activity[2] == data.get('mention')
                from .engagement import quiet
                allowed = settings.idle_enabled and (store.idle_allowed(group, minutes=settings.idle_minutes, limit=settings.idle_daily_limit) or (continuing and not quiet(time.time())))
                return {'allowed': bool(allowed), 'mention': activity[2] if activity else None}
            if operation == 'idle_record':
                store.record_idle(str(data['group']), str(data.get('text', '')))
                return {'ok': True}
            if operation != 'action':
                raise ValueError('operation')
            action, params = data['action'], data.get('params') or {}
            # The runtime may query OneBot and deliver normal messages/files, but does not
            # receive an unrestricted path to QQ administration or device/login controls.
            allowed = action.startswith('get_') or action in {
                'send_group_msg', 'send_private_msg', 'send_msg', 'upload_group_file', 'upload_private_file',
                'send_group_forward_msg', 'send_private_forward_msg', 'send_like', 'set_input_status',
            }
            if not allowed or '/' in action or '?' in action:
                return {'status': 'failed', 'retcode': 403, 'message': 'action requires explicit authorization'}
            group = str(params.get('group_id', ''))
            if group and settings.allowed_groups != '*' and group not in settings.allowed_groups.split(','):
                return {'status': 'failed', 'retcode': 403, 'message': 'group outside scope'}
            response = await app.state.account_client.post('/' + action, json=params)
            response.raise_for_status()
            body = response.json()
            if action in {'send_group_msg','send_private_msg','send_msg'} and body.get('retcode') == 0:
                status.update(last_reply_at=time.time(), last_error=None)
            return body
        except (ValueError, KeyError, TypeError):
            return JSONResponse({'ok': False}, status_code=400)
