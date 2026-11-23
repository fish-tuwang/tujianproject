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
from urllib.parse import unquote, urlsplit

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
        guard=json.loads((ROOT.parent/'guard-state.json').read_text())
        if (0<=checked-float(guard.get('checked_at',0))<=90
            and guard.get('status')=='login_required' and guard.get('requires_login')):
            return {**base,'state':'scan','category':'login_required',
                    'reason':'QQ守护器已确认需要手机登录，请扫码确认；未循环重登'}
    except (OSError,ValueError,TypeError):pass
    try:
        info=gateway({'operation':'action','action':'get_login_info','params':{}})
        if info.get('retcode')!=0:
            return {**base,'state':'error','category':'qq_rpc_failed','reason':'QQ接口未成功返回；尚不能判定掉线'}
        if str((info.get('data') or {}).get('user_id'))!=str(account):
            return {**base,'state':'error','category':'account_mismatch','reason':'QQ身份与配置不匹配，未尝试登录'}
        connection=gateway({'operation':'action','action':'get_status','params':{}})
        online=(connection.get('data') or {}).get('online') if connection.get('retcode')==0 else None
        if online is True:
            try:
                delivery=json.loads((ROOT/'delivery-state.json').read_text())
                if (delivery.get('category')=='qq_network_error'
                    and delivery.get('consecutive_network_failures',0)>=3
                    and 0<=checked-delivery.get('checked_at',0)<300
                    and delivery.get('checked_at',0)-delivery.get('network_failure_since',checked)>=60):
                    return {**base,'state':'error','category':'transport_stalled',
                            'reason':'QQ登录接口显示在线，但持续发送网络异常，收发链路不可用；不能视为正常在线'}
            except (OSError,ValueError,TypeError):pass
            return {**base,'state':'ok','category':'online'}
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


def connection_diagnostics(account):
    result = qq_status(account)
    for name, filename, keys in [
        ('guard', ROOT.parent/'guard-state.json', ('status','reason','checked_at','requires_login',
          'quick_login_eligible','last_online_at','next_retry','last_outage','history')),
        ('delivery', ROOT/'delivery-state.json', ('checked_at','action','ok','category','retcode')),
    ]:
        try:
            value = json.loads(filename.read_text())
            result[name] = {key:value.get(key) for key in keys if key in value}
        except (OSError,ValueError,TypeError):
            result[name] = {'unavailable':True}
    return result


def local_media_path(source):
    """Decode file URIs once; a raw filesystem name may contain a literal %."""
    source = str(source)
    if source.startswith('file:'):
        uri = urlsplit(source)
        if uri.netloc not in {'', 'localhost'}:
            raise ValueError('remote_file_host')
        return Path(unquote(uri.path)).expanduser()
    if '://' in source:
        return None
    return Path(source).expanduser()


def compatible_picture(path):
    """QQNT's WebP upload is unreliable; keep originals and encode the wire copy."""
    from PIL import Image, ImageSequence
    with Image.open(path) as picture:
        if picture.format != 'WEBP':
            return path.read_bytes()
        output = io.BytesIO()
        if getattr(picture, 'n_frames', 1) > 1:
            frames = [frame.convert('RGBA').copy() for frame in ImageSequence.Iterator(picture)]
            durations = []
            for i in range(picture.n_frames):
                picture.seek(i); durations.append(picture.info.get('duration', 100))
            frames[0].save(output, format='GIF', save_all=True, append_images=frames[1:],
                           duration=durations, loop=picture.info.get('loop', 0), disposal=2)
        else:
            picture.convert('RGBA').save(output, format='PNG')
        return output.getvalue()


def delivery_error(result):
    message = str(result.get('message') or result.get('wording') or '').lower()
    if 'rich media transfer failed' in message:
        return 'qq_media_upload_failed', 'QQ媒体上传失败；图片已在本机读取，腾讯端未确认收图'
    if 'enoent' in message or 'no such file' in message:
        return 'qq_media_missing', 'QQ端找不到媒体文件，请检查容器中的媒体路径'
    if '网络连接异常' in message or '1006514' in message or 'network' in message:
        return 'qq_network_error', 'QQ发送网络连接异常；当前登录可能仍有效，请勿反复扫码或重登'
    if 'timeout' in message or 'timed out' in message:
        return 'qq_timeout', 'QQ发送超时，结果尚未确认，请先查看聊天再决定是否重发'
    return 'qq_send_failed', 'QQ拒绝了本次发送，请查看登录状态与群发言权限'


def note_delivery(action,result,now=None):
    """Persist evidence, not a boolean that cached QQ online status can hide."""
    try:
        try:from fatfish_extensions import common
        except ImportError:from qqbot.fatfish_extensions import common
        now=time.time() if now is None else now
        path=ROOT/'delivery-state.json'
        with common.locked(path):
            old=common.read(path,{})
            success=result.get('retcode')==0
            category='ok' if success else delivery_error(result)[0]
            value={'checked_at':now,'action':action,'ok':success,'category':category,'retcode':result.get('retcode')}
            if category=='qq_network_error':
                continuing=old.get('category')==category and 0<=now-old.get('checked_at',0)<300
                value['consecutive_network_failures']=old.get('consecutive_network_failures',0)+1 if continuing else 1
                value['network_failure_since']=old.get('network_failure_since',now) if continuing else now
            else:value['consecutive_network_failures']=0
            if success:value['last_success_at']=now
            elif old.get('last_success_at'):value['last_success_at']=old['last_success_at']
            common.write(path,value)
    except (OSError,ValueError,TypeError):
        pass  # Diagnostics must never change the result or cause a duplicate send.


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
            path = local_media_path(source)
            if path is None:
                continue
            if not path.is_file():
                raise ValueError('local_media_missing')
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
            raw = compatible_picture(path) if segment['type'] == 'image' else path.read_bytes()
            segment['data']['file'] = 'base64://' + base64.b64encode(raw).decode()
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
    import shutil
    sing=importlib.import_module('sing')
    songs=ROOT/'songs'
    if not songs.exists():
        if (path/'songs').is_dir():shutil.copytree(path/'songs',songs)
        else:songs.mkdir(parents=True)
    sing.SONG_DIR=songs;sing.INDEX=songs/'songs.json'
    return importlib.import_module(name)


def refresh_login_qr():
    """Explicit owner action only. Wait for a new image; never restart the account."""
    import importlib.util
    spec=importlib.util.spec_from_file_location('mac_qq_guard',ROOT.parent/'guard.py')
    guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)
    try:
        api=guard.WebUI(ROOT.parent);api.auth();state=api.post('/QQLogin/CheckLoginStatus') or {}
        if state.get('isLogin'):
            return {'ok':True,'message':'QQ已登录，不刷新、不重新登录'}
        if state.get('loginPhase') in {'qrcode_scanned','initializing','reconnecting'}:
            return {'ok':False,'error':'QQ正在确认或恢复连接，请稍后查看状态，不打断当前登录'}
        if guard.VERIFY.search(str(state.get('loginError',''))):
            return {'ok':False,'error':'QQ要求手机安全验证，请先在手机完成验证；当前状态已保留'}
        def copy_qr():
            p=subprocess.run(['docker','exec','little-atlas-mac-qq-account-1','cat','/app/napcat/cache/qrcode.png'],capture_output=True,timeout=5)
            return p.stdout if p.returncode==0 else b''
        old=copy_qr();api.post('/QQLogin/RefreshQRcode',{})
        for _ in range(20):
            time.sleep(.5);data=copy_qr()
            if data and data!=old and data.startswith(b'\x89PNG\r\n\x1a\n'):
                from PIL import Image
                try:
                    with Image.open(io.BytesIO(data)) as image:image.verify()
                except (OSError, ValueError):
                    continue
                path=ROOT.parent/'login-qr.png';path.write_bytes(data);path.chmod(0o600)
                return {'ok':True,'img':'data:image/png;base64,'+base64.b64encode(data).decode()}
        return {'ok':False,'error':'未取得更新后的二维码，请稍后重试；没有重启或重登'}
    except Exception:
        return {'ok':False,'error':'QQ登录管理接口暂不可用；保留当前状态，未重启或重登'}


async def run_bot():
    module = load_module('bot')
    # v1.18.2's public galgame stub omits a function used by its public bot.py.
    if not hasattr(module.galgame, 'stage'):
        module.galgame.stage = lambda value: (0, '普通群友')
    bubble = contextvars.ContextVar('bubble', default=None)
    last_failure = contextvars.ContextVar('last_delivery_failure', default=None)
    original_admin_send = module.FatFish._admin_send
    async def admin_send(self, params):
        token = last_failure.set(None)
        try:
            result = await original_admin_send(self, params)
            failure = last_failure.get()
            if failure and result.get('error'):
                result['error'] = failure[1]
                result['error_code'] = failure[0]
            return result
        finally:
            last_failure.reset(token)
    module.FatFish._admin_send = admin_send
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
            try:
                params = await asyncio.to_thread(rotate_images, group, params)
            except (ValueError, OSError):
                return {'retcode':400,'status':'failed','message':'本机图片或语音不可用，请刷新素材后重试'}
            if not params.get('message'):
                return {'retcode':403,'status':'failed','message':'no non-repeating content'}
        # Native QQ file upload needs a path inside the existing account container.
        if action in {'upload_group_file','upload_private_file'}:
            file = local_media_path(params.get('file',''))
            if file is None:
                return {'retcode':403,'status':'failed','message':'file outside runtime'}
            file = file.resolve()
            if not file.is_file() or ROOT.resolve() not in file.parents:
                return {'retcode':403,'status':'failed','message':'file outside runtime'}
            target = '/tmp/fatfish-' + hashlib.sha256(file.read_bytes()).hexdigest()[:20] + file.suffix
            result = await asyncio.to_thread(subprocess.run, ['docker','cp',str(file),'little-atlas-mac-qq-account-1:'+target], capture_output=True)
            if result.returncode: return {'retcode':-1,'status':'failed'}
            params = {**params,'file':target}
        result = await call_gateway({'operation':'action','action':action,'params':params})
        if action in {'send_group_msg','send_private_msg','send_msg'}:
            success = result.get('retcode') == 0
            category, explanation = ('ok', '') if success else delivery_error(result)
            if not success:
                last_failure.set((category, explanation))
            note_delivery(action,result)
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
    panel.BACKUP=ROOT/'backups';panel.LOG=ROOT/'bot.log'
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
        if url=='/api/mac-qq-login':
            return refresh_login_qr() if body=={'action':'refresh'} else {'ok':False,'error':'不支持的登录操作'}
        if url == '/api/bot':
            action = body.get('action')
            if action in {'start','start_all','restart','force_restart','restart_hard'}:
                ok, message = service('restart');return {'ok':ok,'msg':message}
            if action in {'stop','shutdown','stop_all'}:
                ok, message = service('stop');return {'ok':ok,'msg':message}
            return {'ok':False,'error':'为保留在线服务，请使用重启聊天机器人'}
        return original(self, url, body)
    panel.H.route = route
    original_get=panel.H.do_GET
    def get(self):
        if self.path.split('?',1)[0]=='/api/mac-qq-status':
            if not self._host_ok():return self._json({'ok':False},403)
            return self._json(connection_diagnostics(panel.cfg().get('bot_qq')))
        return original_get(self)
    panel.H.do_GET=get
    panel.serve(quiet=True)


if __name__ == '__main__':
    if '--panel' in sys.argv: run_panel()
    else: asyncio.run(run_bot())
