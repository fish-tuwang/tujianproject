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
    try:
        p = subprocess.run(['docker', 'exec', '-i', CONTAINER, 'python', '-c', GATEWAY], input=json.dumps(data).encode(), capture_output=True, timeout=70)
    except FileNotFoundError:
        raise RuntimeError('docker_unavailable') from None
    except subprocess.TimeoutExpired:
        raise RuntimeError('gateway_timeout') from None
    if p.returncode:
        error=p.stderr.decode('utf-8',errors='replace')
        category='gateway_unavailable'
        if 'HTTP Error 403' in error:category='gateway_auth_failed'
        elif 'No such container' in error:category='bridge_missing'
        elif 'is not running' in error:category='bridge_stopped'
        elif 'Cannot connect to the Docker daemon' in error:category='docker_unavailable'
        raise RuntimeError(category)
    try:
        result=json.loads(p.stdout)
        if not isinstance(result,dict):raise ValueError('response')
        return result
    except ValueError:
        raise RuntimeError('gateway_invalid_response') from None


def qq_status(account):
    """Do not turn a failed probe or stale identity into a login diagnosis."""
    checked=time.time()
    base={'account':str(account),'checked_at':checked}
    try:
        info=gateway({'operation':'action','action':'get_login_info','params':{}})
        if info.get('retcode')!=0:
            return {**base,'state':'error','category':'qq_rpc_failed','reason':'QQ接口未成功返回；尚不能判定掉线'}
        if str((info.get('data') or {}).get('user_id'))!=str(account):
            return {**base,'state':'error','category':'account_mismatch','reason':'QQ身份与配置不匹配，未尝试登录'}
        connection=gateway({'operation':'action','action':'get_status','params':{}})
        online=(connection.get('data') or {}).get('online') if connection.get('retcode')==0 else None
        if online is True:return {**base,'state':'ok','category':'online'}
        if online is not False:
            return {**base,'state':'error','category':'qq_status_unknown','reason':'QQ在线检查未成功，保留现有登录'}
        file=ROOT.parent/'guard-state.json'
        guard=json.loads(file.read_text()) if file.exists() else {}
        fresh=0<=checked-float(guard.get('checked_at',0))<=90
        if fresh and guard.get('status')=='login_required':
            return {**base,'state':'scan','category':'login_required','reason':'守护器确认需要手机验证，未自动重登',
                    'qr_t':(ROOT.parent/'login-qr.png').stat().st_mtime if (ROOT.parent/'login-qr.png').exists() else 0}
        return {**base,'state':'offline','category':'qq_offline','reason':'QQ接口明确返回离线；等待原守护器限频恢复'}
    except (RuntimeError,OSError,ValueError,TypeError) as error:
        known={'docker_unavailable','gateway_timeout','gateway_auth_failed','bridge_missing','bridge_stopped',
               'gateway_unavailable','gateway_invalid_response'}
        category=str(error) if str(error) in known else 'probe_error'
        return {**base,'state':'error','category':category,'reason':'QQ探测失败，未判定掉线或触发重登'}


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
    sys.path.insert(0, str(ROOT/'extensions/current'))
    try:
        from fatfish_extensions import install
    except ImportError:
        from qqbot.fatfish_extensions import install
    install(path)
    return importlib.import_module(name)


async def run_bot():
    module = load_module('bot')
    # v1.18.2's public galgame stub omits a function used by its public bot.py.
    if not hasattr(module.galgame, 'stage'):
        module.galgame.stage = lambda value: (0, '普通群友')
    bubble = contextvars.ContextVar('bubble', default=None)
    original_handle = module.FatFish.handle
    async def handle(self,event,catch=None):
        # Explicit "remember" statements should work immediately, rather than waiting
        # for the regular batched background distillation threshold.
        if catch is None and event.get('post_type')=='message' and event.get('message_type')=='group':
            segments=event.get('message') or []
            if isinstance(segments,list) and any(s.get('type')=='at' and str(s.get('data',{}).get('qq'))==str(event.get('self_id')) for s in segments):
                text=''.join(str(s.get('data',{}).get('text','')) for s in segments if s.get('type')=='text').strip()
                import re
                match=re.search(r'(?:请)?记住[：:,，\s]*(我.{1,180})',text)
                if match and not module.memory.is_injection(match.group(1)):
                    key='group_'+str(event['group_id']);uid=str(event['user_id']);name=module.sender_name(event)
                    async with module.mem_lock(key):
                        mem=module.load_mem(key,'group')
                        module.memory.apply2(mem,[{'text':match.group(1),'uid':uid,'who':name,'pin':True,'src':[1],'evidence':match.group(1),'kind':'fact','imp':4}],daily_cap=40,lines=[{'role':'user','text':text,'uid':uid,'name':name,'mid':event.get('message_id'),'ts':time.time()}])
                        module.save_mem(mem)
        return await original_handle(self,event,catch=catch)
    module.FatFish.handle=handle
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
    try:
        from fatfish_extensions.panel import install as install_core_panel
    except ImportError:
        from qqbot.fatfish_extensions.panel import install as install_core_panel
    install_core_panel(panel)
    panel.QRCODE = ROOT.parent / 'login-qr.png'
    panel.qq_status = lambda: qq_status(panel.cfg().get('bot_qq'))
    panel.napcat_up = lambda: panel.qq_status()['state'] == 'ok'
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
    original_get=panel.H.do_GET
    def get(self):
        if self.path.split('?',1)[0]=='/api/mac-qq-status':
            if not self._host_ok():return self._json({'ok':False},403)
            return self._json(panel.qq_status())
        return original_get(self)
    panel.H.do_GET=get
    panel.serve(quiet=True)


if __name__ == '__main__':
    if '--panel' in sys.argv: run_panel()
    else: asyncio.run(run_bot())
