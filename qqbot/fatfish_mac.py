"""macOS adapter for the unmodified public FatFish runtime and control panel.

The QQ account remains in its existing Docker container. Only authenticated
OneBot requests/events cross the local gateway; no second QQ login is started.
"""
import asyncio
import base64
import contextvars
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

ROOT = Path.home() / 'Library/Application Support/LittleAtlasQQ/fatfish'
CONTAINER = 'little-atlas-mac-qq-bridge-1'
GATEWAY = '''import json,os,sys,urllib.request
body=sys.stdin.buffer.read()
r=urllib.request.Request('http://127.0.0.1:8096/admin/fatfish',data=body,headers={'Authorization':'Bearer '+os.environ['QQ_ONEBOT_TOKEN'],'Content-Type':'application/json'})
with urllib.request.urlopen(r,timeout=65) as f:sys.stdout.buffer.write(f.read())
'''


def gateway(data):
    p = subprocess.run(['docker', 'exec', '-i', CONTAINER, 'python', '-c', GATEWAY], input=json.dumps(data).encode(), capture_output=True, timeout=70)
    if p.returncode:
        raise RuntimeError('local QQ gateway unavailable')
    return json.loads(p.stdout)


async def call_gateway(data):
    return await asyncio.to_thread(gateway, data)


def rotate_images(group, params, *, remember=False):
    """Compare decoded pictures, not filenames/captions, across runtime restarts."""
    from PIL import Image
    params = json.loads(json.dumps(params))
    message = params.get('message')
    if not isinstance(message, list):
        return params
    database = ROOT / 'image-history.sqlite3'
    with sqlite3.connect(database) as db:
        db.execute('CREATE TABLE IF NOT EXISTS pictures (place TEXT,key TEXT,at REAL)')
        recent = [r[0] for r in db.execute('SELECT key FROM pictures WHERE place=? ORDER BY at DESC LIMIT 3', (str(group),))]
        def fingerprint(path):
            with Image.open(path) as picture:
                picture = picture.convert('RGBA')
                return hashlib.sha256(str(picture.size).encode() + picture.tobytes()).hexdigest()
        for segment in message:
            if segment.get('type') not in {'image', 'record'}:
                continue
            source = str(segment.get('data', {}).get('file', ''))
            path = Path(source.removeprefix('file://'))
            if not path.is_file():
                continue
            if segment['type'] == 'image':
                key = fingerprint(path)
                if recent and key == recent[0]:
                    index = json.loads((ROOT / 'stickers/index.json').read_text()).get('stickers', {})
                    old = index.get(path.stem, {})
                    candidates = [ROOT / 'stickers' / v.get('file', '') for v in index.values() if isinstance(v, dict) and v.get('emo') == old.get('emo')]
                    candidates = [p for p in candidates if p.is_file() and fingerprint(p) not in recent]
                    if not candidates:
                        candidates = [p for p in ROOT.joinpath('stickers').glob('*') if p.is_file() and p.suffix.lower() in {'.png','.jpg','.webp','.gif'} and p.stem.startswith('sleep-') == path.stem.startswith('sleep-') and fingerprint(p) != key]
                    if candidates:
                        path = candidates[0]; key = fingerprint(path)
                    else:
                        segment.clear(); continue
                if remember:
                    db.execute('INSERT INTO pictures VALUES(?,?,?)', (str(group), key, time.time()))
            segment['data']['file'] = 'base64://' + base64.b64encode(path.read_bytes()).decode()
        params['message'] = [s for s in message if s]
        if not any(s.get('type') == 'text' and s.get('data', {}).get('text', '').strip() for s in params['message']):
            params['message'] = [s for s in params['message'] if s.get('type') not in {'reply','text'}]
    return params


def load_module(name):
    path = ROOT / 'current/bot'
    sys.path.insert(0, str(path))
    return importlib.import_module(name)


async def run_bot():
    module = load_module('bot')
    # v1.18.2's public galgame stub omits a function used by its public bot.py.
    if not hasattr(module.galgame, 'stage'):
        module.galgame.stage = lambda value: (0, '普通群友')
    bubble = contextvars.ContextVar('bubble', default=None)
    class Socket:
        def __aiter__(self): return self
        async def __anext__(self):
            while True:
                try:
                    value = await call_gateway({'operation': 'poll'})
                    if value.get('event'):
                        return json.dumps(value['event'], ensure_ascii=False)
                except Exception:
                    await asyncio.sleep(3)
    class Connection:
        async def __aenter__(self): return Socket()
        async def __aexit__(self, *args): return False
    module.websockets.connect = lambda *args, **kwargs: Connection()

    async def call(self, action, _timeout=20, **params):
        idle = bubble.get()
        if idle and action.startswith('send_') and not (await call_gateway({'operation':'idle_check','group':idle['group'], 'continuing':idle['recorded'], 'human':idle['human']})).get('allowed'):
            return {'retcode':403,'status':'failed','message':'idle cancelled by current activity or quiet hours'}
        group = str(params.get('group_id') or params.get('user_id') or '')
        original = params
        if action in {'send_group_msg','send_private_msg','send_msg'}:
            params = await asyncio.to_thread(rotate_images, group, params)
            if not params.get('message'):
                return {'retcode':403,'status':'failed','message':'no non-repeating content'}
        # Native QQ file upload needs a path inside the existing account container.
        if action in {'upload_group_file','upload_private_file'}:
            file = Path(str(params.get('file',''))).expanduser().resolve()
            if not file.is_file() or ROOT.resolve() not in file.parents:
                return {'retcode':403,'status':'failed','message':'file outside runtime'}
            target = '/tmp/fatfish-' + hashlib.sha256(file.read_bytes()).hexdigest()[:20] + file.suffix
            result = await asyncio.to_thread(subprocess.run, ['docker','cp',str(file),'little-atlas-mac-qq-account-1:'+target], capture_output=True)
            if result.returncode: return {'retcode':-1,'status':'failed'}
            params = {**params,'file':target}
        result = await call_gateway({'operation':'action','action':action,'params':params})
        if result.get('retcode') == 0 and action in {'send_group_msg','send_private_msg','send_msg'}:
            await asyncio.to_thread(rotate_images, group, original, remember=True)
            if idle and not idle['recorded']:
                await call_gateway({'operation':'idle_record','group':idle['group'],'text':'FatFish idle message'})
                idle['recorded'] = True
        return result
    module.FatFish.call = call
    original_bubble = module.FatFish._bubble
    async def bounded_bubble(self, group, cfg):
        eligibility = await call_gateway({'operation':'idle_check','group':group})
        if not eligibility.get('allowed'):return
        token = bubble.set({'group':group,'recorded':False,'human':eligibility.get('human')})
        try: await original_bubble(self, group, cfg)
        finally: bubble.reset(token)
    module.FatFish._bubble = bounded_bubble
    async def idle_loop(self):
        while True:
            await asyncio.sleep(60)
            try:
                for group in (await call_gateway({'operation':'idle_candidates'})).get('groups',[]):
                    await self._bubble(group, module.CFG.get('speakup') or {})
            except Exception as error:
                module.log('[Mac冒泡]', type(error).__name__)
    module.FatFish.speakup_loop = idle_loop
    return await module.main()


def run_panel():
    panel = load_module('panel')
    panel.QRCODE = ROOT.parent / 'login-qr.png'
    def qq_status():
        try:
            info = gateway({'operation':'action','action':'get_login_info','params':{}})
            online = info.get('retcode') == 0 and str((info.get('data') or {}).get('user_id')) == str(panel.cfg().get('bot_qq'))
            return {'state':'ok' if online else 'starting','account':str(panel.cfg().get('bot_qq'))}
        except Exception:return {'state':'starting','account':str(panel.cfg().get('bot_qq'))}
    panel.qq_status = qq_status
    panel.napcat_up = lambda: qq_status()['state'] == 'ok'
    panel.qq_running = lambda: True
    panel.bot_procs = lambda: []
    panel.ws_clients = lambda: False
    def service(action):
        target = 'gui/' + str(os.getuid()) + '/com.little-atlas.fatfish'
        command = ['launchctl','kickstart','-k',target] if action in {'start','restart'} else ['launchctl','bootout',target]
        result = subprocess.run(command, capture_output=True)
        if result.returncode and action in {'start','restart'}:
            result = subprocess.run(['launchctl','bootstrap','gui/'+str(os.getuid()),str(Path.home()/'Library/LaunchAgents/com.little-atlas.fatfish.plist')],capture_output=True)
        return result.returncode == 0, 'Mac 聊天服务已处理，QQ 登录保持不变'
    panel.start_bot = lambda: service('start')
    panel.start_all = panel.start_bot
    panel.stop_all = lambda: (False, '账号服务由 Mac 守护器管理；请只重启聊天机器人')
    original = panel.H.route
    def route(self, url, body):
        if url == '/api/bot':
            action = body.get('action')
            if action in {'start','start_all','restart','force_restart'}:
                ok, message = service('restart');return {'ok':ok,'msg':message}
            if action == 'stop':
                ok, message = service('stop');return {'ok':ok,'msg':message}
            return {'ok':False,'error':'为保留在线服务，请使用重启聊天机器人'}
        return original(self, url, body)
    panel.H.route = route
    panel.serve(quiet=True)


if __name__ == '__main__':
    if '--panel' in sys.argv: run_panel()
    else: asyncio.run(run_bot())
