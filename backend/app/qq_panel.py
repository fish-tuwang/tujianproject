"""Owner-only Mac panel proxy with a scoped NetEase QR-login exception."""
import json
import re

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from .audit import audit

router=APIRouter()
PREFIX='/qq-panel'
NO_STORE={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer'}

REMOTE_CONTROLS='''<script>(()=>{
const original=window.fetch.bind(window);
const checked=async(...args)=>{
 const r=await original(...args);
 if(r.status===401&&new URL(r.url||location.href).origin===location.origin){
  try{const d=await r.clone().json();if(d.code==='AUTH_REQUIRED'){location.assign('/login/?next='+encodeURIComponent(location.pathname+location.hash));throw Error('图鉴登录已失效，请重新登录控制面板');}}catch(error){if(error.message.includes('图鉴登录已失效'))throw error;}
 }
 return r;
};
window.fetch=async(input,options={})=>{
 const url=new URL(typeof input==='string'?input:input.url,location.href);
 if(url.origin!==location.origin||!url.pathname.startsWith('/qq-panel/api/')||String(options.method||'GET').toUpperCase()!=='POST')return checked(input,options);
 let body;try{body=JSON.parse(options.body||'{}');}catch(e){return checked(input,options);}
 const path=url.pathname.slice('/qq-panel/'.length);
 if(path==='api/tool'){
  if(body.name==='open_logs'){location.hash='logs';return new Response(JSON.stringify({ok:true,msg:'已打开日志页'}),{headers:{'Content-Type':'application/json'}});}
  return new Response(JSON.stringify({ok:false,error:'这是Mac本机安装/文件夹操作；远程可使用日志、歌单与表情管理页面'}),{status:400,headers:{'Content-Type':'application/json'}});
 }
 const dangerous=['api/wipe','api/memory/forget','api/songs/delete','api/mac-qq-login'].includes(path)
  ||path==='api/bot'&&!['start','start_all'].includes(body.action)
  ||path==='api/music/login'&&body.action==='logout'
  ||path==='api/local-core'&&['self_remove','diary_archive','event_remove'].includes(body.action)
  ||['api/fixup','api/tasks','api/prank','api/person/impression'].includes(path)&&['del','delete','clear','cl_del','cancel','prom_del','send','schedule','next','undo'].includes(body.op||body.action)
  ||path==='api/qzone'&&!['status','pause','resume','selftest'].includes(body.what);
 if(dangerous){
  const message=path==='api/wipe'?'将删除指定用户的聊天和记忆数据。确认继续？':path==='api/bot'?'将操作聊天进程，QQ账号和登录数据保持不变。确认继续？':'此操作会删除、退出登录或执行对外操作。确认继续？';
  if(!window.confirm(message))return new Response(JSON.stringify({ok:false,error:'操作已取消'}),{status:409,headers:{'Content-Type':'application/json'}});
  const headers=new Headers(options.headers||{});headers.set('X-Panel-Confirm','1');options={...options,headers};
 }
 return checked(input,options);
};
let qrRefreshing=false;
document.addEventListener('click',async event=>{
 const button=event.target.closest('[data-qq-qr-refresh]');if(!button||qrRefreshing)return;
 qrRefreshing=true;button.disabled=true;button.textContent='刷新中…';const note=button.parentElement.querySelector('[role="status"]');note.textContent='正在获取新二维码…';
 try{
  const r=await checked('/qq-panel/api/mac-qq-login',{method:'POST',headers:{'Content-Type':'application/json','X-Panel':'1','X-Panel-Confirm':'1'},body:JSON.stringify({action:'refresh'})});
  const d=await r.json();if(!r.ok||!d.ok)throw Error(d.error||'刷新失败');
  if(d.img){const image=button.parentElement.querySelector('img.qr');await new Promise((resolve,reject)=>{const timeout=setTimeout(()=>finish(Error('二维码加载超时，请重试')),10000);function finish(error){clearTimeout(timeout);image.onload=null;image.onerror=null;error?reject(error):resolve();}image.onload=()=>finish();image.onerror=()=>finish(Error('二维码加载失败，请重试'));image.src='/qq-panel/qrcode?t='+Date.now();});note.textContent='已刷新，请扫码';}
  else note.textContent=d.message||'QQ已在线，无需扫码';
 }catch(error){note.textContent=error.message||'刷新失败，请重试';}
 finally{button.disabled=false;button.textContent='刷新二维码';qrRefreshing=false;}
});
})();</script>'''

QQ_LOGIN_HTML='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>QQ登录与诊断</title><style>body{font:16px/1.8 system-ui;background:#eef4f6;color:#12222b;max-width:800px;margin:40px auto;padding:20px}section{background:white;padding:28px;border-radius:16px}button{padding:12px;cursor:pointer}img{display:block;width:min(280px,100%);height:auto;image-rendering:pixelated;margin:20px auto}img[hidden]{display:none}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style><body><a href="/qq-panel/">← 返回控制面板</a><section><h1>QQ登录与连接诊断</h1><p>仅刷新登录二维码，不重启QQ、不删除登录数据。已在线时不会重新登录。</p><pre id="status">读取状态中…</pre><pre id="diagnostics" aria-label="连接保护与最近故障"></pre><p id="message" role="status"></p><a id="login-again" href="/login/?next=%2Fqq-panel%2Fqq-login" hidden>重新登录图鉴后查看二维码</a><img id="qr" alt="QQ登录二维码" hidden><button id="refresh" style="display:block;margin:12px auto;background:#126a85;color:white;border:0;border-radius:10px;min-width:180px;font-weight:600">刷新二维码</button></section><script>
const el=id=>document.getElementById(id);const fmt=t=>Number.isFinite(t)&&t>0?new Date(t*1000).toLocaleString('zh-CN'):'暂无记录';
const labels={transport_stalled:'QQ假在线：持续发送失败，收发不可用',online:'QQ在线',offline:'QQ离线',probe_error:'探测失败（不代表掉线）',login_required:'需要手机登录',recovering:'正在确认/恢复连接',rate_limited:'达到重试上限，等待冷却',quick_login_requested:'已请求保存的快速登录',starting_account:'正在恢复停止的账号服务',restarting_stale_client:'正在恢复陈旧登录进程'};
async function status(){try{const r=await fetch('/qq-panel/api/mac-qq-status',{cache:'no-store'});const d=await r.json();if(!r.ok){el('qr').hidden=true;el('message').textContent='';el('login-again').hidden=d.code!=='AUTH_REQUIRED';throw Error(d.code==='AUTH_REQUIRED'?'图鉴登录已失效，请重新登录控制面板':'状态接口暂不可用，不能据此判定掉线');}el('login-again').hidden=true;el('status').textContent=(d.state==='ok'?'QQ当前在线':d.reason||d.category||'暂无法确认状态')+'\\n检查时间：'+fmt(d.checked_at);
 const g=d.guard||{},m=d.delivery||{};const fresh=g.checked_at&&Date.now()/1000-g.checked_at<90;
 const rows=['连接保护：'+(fresh?(labels[g.status]||'状态待确认'):'状态尚未更新'), '快速登录：'+(g.quick_login_eligible===true?'有可用记录':g.quick_login_eligible===false?'无可用记录，失效后需要手机扫码':'尚未确认'), '最近确认在线：'+fmt(g.last_online_at)];
 if(g.last_outage)rows.push('最近一次离线持续：'+Math.round(g.last_outage.seconds)+' 秒');
 if(g.next_retry>Date.now()/1000)rows.push('下次允许重试：'+fmt(g.next_retry));
 if(m.checked_at)rows.push('最近发送：'+fmt(m.checked_at)+' · '+(m.ok?'QQ接口返回成功':m.category==='qq_media_upload_failed'?'媒体上传失败（不等于掉线）':m.category==='qq_network_error'?'QQ发送网络异常（不等于登录失效）':m.category||'发送未成功'));
 const history=(g.history||[]).slice(-5);if(history.length)rows.push('最近状态变化：',...history.map(e=>fmt(e.at)+' '+(labels[e.to]||e.to)));
 el('diagnostics').textContent=rows.join('\\n');if(d.state==='ok'){el('qr').hidden=true;el('message').textContent='QQ已在线，无需扫码。';}else if(d.state==='scan'){try{await showQR();el('message').textContent='请用机器人账号的手机QQ扫码；若提示过期，点击获取新二维码。';}catch(error){el('message').textContent=error.message;}}}catch(e){el('status').textContent=e.message||'状态接口暂不可用，不能据此判定掉线。';el('diagnostics').textContent='';}}

let qrLoadedAt=0,qrLoad=null;
async function showQR(force=false){
 const img=el('qr');if(!force&&!img.hidden&&Date.now()-qrLoadedAt<30000)return;
 if(qrLoad){try{await qrLoad;}catch(error){if(!force)throw error;}if(!force)return;}
 qrLoad=new Promise((resolve,reject)=>{
  const timeout=setTimeout(()=>finish(Error('二维码图片加载超时，请重试')),10000);
  function finish(error){clearTimeout(timeout);img.onload=null;img.onerror=null;if(error){img.hidden=true;reject(error);}else{qrLoadedAt=Date.now();img.hidden=false;resolve();}}
  img.onload=()=>finish();img.onerror=()=>finish(Error('二维码图片未加载，请重新登录面板或点击获取新二维码'));
  img.src='/qq-panel/qrcode?t='+Date.now();
 });
 try{await qrLoad;}finally{qrLoad=null;}
}

el('refresh').onclick=async()=>{el('refresh').disabled=true;el('refresh').textContent='刷新中…';el('message').textContent='正在获取新二维码…';try{const r=await fetch('/qq-panel/api/mac-qq-login',{method:'POST',headers:{'Content-Type':'application/json','X-Panel':'1','X-Panel-Confirm':'1'},body:JSON.stringify({action:'refresh'})});const d=await r.json();if(!r.ok||!d.ok)throw Error(d.error||'刷新失败');if(d.img){await showQR(true);el('message').textContent='二维码已刷新，请扫码并在手机确认。';}else el('message').textContent=d.message||'QQ已在线';}catch(e){el('message').textContent=e.message;}finally{el('refresh').disabled=false;el('refresh').textContent='刷新二维码';}};status();setInterval(status,10000);
</script></body></html>'''


async def netease_login(request):
    # Never forward the catalog cookie, arbitrary JSON, or upstream Set-Cookie.
    # Public TLS terminates at Nginx; the Mac API may see HTTP over the tunnel.
    origin=str(request.url.replace(scheme='https',path='',query='',fragment='')).rstrip('/')
    if (request.headers.get('origin')!=origin or request.headers.get('x-panel')!='1'
            or request.headers.get('sec-fetch-site','same-origin')!='same-origin'):
        return JSONResponse({'ok':False,'error':'请从当前面板发起网易云关联'},status_code=403,headers=NO_STORE)
    if request.headers.get('content-type','').split(';',1)[0].strip().lower()!='application/json':
        return JSONResponse({'ok':False,'error':'请使用JSON提交'},status_code=415,headers=NO_STORE)
    data=bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data)>1024:
            return JSONResponse({'ok':False,'error':'请求过大'},status_code=413,headers=NO_STORE)
    try:
        body=json.loads(data)
    except (ValueError,UnicodeError):
        return JSONResponse({'ok':False,'error':'无效JSON'},status_code=400,headers=NO_STORE)
    if (not isinstance(body,dict) or set(body)!={'platform','action'} or body.get('platform') not in ('netease','qq','kugou')
            or body.get('action') not in ('start','poll','check','logout') or request.url.query):
        return JSONResponse({'ok':False,'error':'无效的音乐平台登录操作'},status_code=403,headers=NO_STORE)
    if body['action']=='logout' and request.headers.get('x-panel-confirm')!='1':
        return JSONResponse({'ok':False,'error':'请先确认退出音乐平台登录'},status_code=409,headers=NO_STORE)
    try:
        async with httpx.AsyncClient(timeout=30,trust_env=False,follow_redirects=False) as client:
            async with client.stream('POST','http://host.docker.internal:8765/api/music/login',json=body,
                                     headers={'Host':'127.0.0.1:8765','X-Panel':'1'}) as result:
                payload=bytearray()
                async for chunk in result.aiter_bytes():
                    payload.extend(chunk)
                    if len(payload)>512*1024:raise ValueError('login response too large')
                if result.status_code!=200:raise ValueError('panel login rejected')
                answer=json.loads(payload)
        if not isinstance(answer,dict) or not isinstance(answer.get('ok'),bool):
            raise ValueError('invalid login response')
        out={'ok':answer['ok']}
        for key in ('state','nick','why','error'):
            if isinstance(answer.get(key),str):out[key]=answer[key][:300]
        for key in ('asked','valid','vip'):
            if answer.get(key) is None or isinstance(answer.get(key),bool):
                if key in answer:out[key]=answer[key]
        if body['action']=='start' and out['ok']:
            img=answer.get('img','')
            if not isinstance(img,str) or not re.fullmatch(r'data:image/(?:png|jpeg|gif|webp);base64,[A-Za-z0-9+/=\r\n]+',img):
                raise ValueError('invalid QR image')
            out['img']=img
        return JSONResponse(out,headers=NO_STORE)
    except (httpx.HTTPError,ValueError,UnicodeError):
        return JSONResponse({'ok':False,'error':'网易云关联接口暂时不可用，请稍后重试'},status_code=503,headers=NO_STORE)


async def panel_send(request):
    origin=str(request.url.replace(scheme='https',path='',query='',fragment='')).rstrip('/')
    if (request.headers.get('origin')!=origin or request.headers.get('x-panel')!='1'
            or request.headers.get('sec-fetch-site','same-origin')!='same-origin' or request.url.query):
        return JSONResponse({'ok':False,'error':'请从当前面板发送消息'},status_code=403,headers=NO_STORE)
    if request.headers.get('content-type','').split(';',1)[0].strip().lower()!='application/json':
        return JSONResponse({'ok':False,'error':'请使用JSON提交'},status_code=415,headers=NO_STORE)
    data=bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data)>8192:return JSONResponse({'ok':False,'error':'消息过长'},status_code=413,headers=NO_STORE)
    try:
        body=json.loads(data)
        if not isinstance(body,dict) or set(body)-{'scene','target','text','sticker','voice','emo','remember'}:raise ValueError()
        if body.get('scene') not in {'group','private'} or not isinstance(body.get('target'),str) or not re.fullmatch(r'[1-9][0-9]{3,11}',body['target']):raise ValueError()
        for name,limit in [('text',500),('sticker',100),('emo',20)]:
            if not isinstance(body.get(name,''),str) or len(body.get(name,''))>limit:raise ValueError()
        if not (body.get('text','').strip() or body.get('sticker','').strip()):raise ValueError()
        for name in ['voice','remember']:
            if name in body and type(body[name]) is not bool:raise ValueError()
    except (ValueError,TypeError,UnicodeError):
        return JSONResponse({'ok':False,'error':'请选择接收对象，并填写文字或选择表情包'},status_code=400,headers=NO_STORE)
    try:
        async with httpx.AsyncClient(timeout=65,trust_env=False,follow_redirects=False) as client:
            response=await client.post('http://host.docker.internal:8765/api/send',json=body,
                headers={'Host':'127.0.0.1:8765','X-Panel':'1'})
            response.raise_for_status();answer=response.json()
        if not isinstance(answer,dict) or type(answer.get('ok')) is not bool:raise ValueError()
        return JSONResponse({'ok':answer['ok'],'error':str(answer.get('error') or '')[:300]},headers=NO_STORE)
    except (httpx.HTTPError,ValueError):
        return JSONResponse({'ok':False,'error':'代发请求未确认成功，请先查看聊天记录，避免重复发送'},status_code=503,headers=NO_STORE)


MANAGEMENT_PATHS={
    'api/bot','api/config','api/control','api/her_blocked','api/person/impression','api/tasks',
    'api/memory/forget','api/memory/add','api/memory/pin','api/memory/unpin','api/memory/restore',
    'api/memory/fade','api/memory/taboo_del','api/memory/consolidate','api/quick','api/qzone',
    'api/prank','api/life','api/fixup','api/favor','api/wipe','api/persona','api/stickers/toggle',
    'api/tts','api/prices','api/music/selftest','api/songs/save','api/songs/upload',
    'api/songs/import','api/songs/preview','api/songs/delete','api/fu_label','api/stickerlib_label',
    'api/stickerdict_edit','api/shadow_label','api/local-core','api/mac-qq-login',
}


def needs_confirmation(path,body):
    if path in {'api/wipe','api/memory/forget','api/songs/delete','api/mac-qq-login'}:return True
    if path=='api/bot':return body.get('action') not in {'start','start_all'}
    if path=='api/music/login':return body.get('action')=='logout'
    if path=='api/local-core':return body.get('action') in {'self_remove','diary_archive','event_remove'}
    if path in {'api/fixup','api/tasks','api/prank','api/person/impression'}:
        return body.get('op',body.get('action')) in {'del','delete','clear','cl_del','cancel','prom_del','send','schedule','next','undo'}
    if path=='api/qzone':return body.get('what') not in {'status','pause','resume','selftest'}
    return False


def validate_management(path,body):
    if not isinstance(body,dict):raise ValueError('请求必须为JSON对象')
    if path=='api/bot' and body.get('action') not in {'start','start_all','restart','restart_hard','force_restart','stop','shutdown','stop_all'}:
        raise ValueError('只允许管理聊天进程，不重建或清空QQ登录')
    if path=='api/mac-qq-login' and body!={'action':'refresh'}:raise ValueError('只允许刷新QQ登录二维码')
    if path=='api/config':
        changes=body.get('changes')
        if not isinstance(changes,list) or len(changes)>150:raise ValueError('配置项格式不正确')
        for change in changes:
            if not isinstance(change,dict) or set(change)!={'path','value'}:raise ValueError('配置项格式不正确')
            key=change.get('path')
            if not isinstance(key,str) or not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_]*(?:\.[a-zA-Z0-9_]+)*',key):raise ValueError('配置路径不正确')
            if key.split('.')[0] in {'onebot','panel','persona_file','bot_qq','owner_qq','group_card','profile'}:raise ValueError('账号、设备、管理鉴权与文件路径配置仅能在本机维护')
            if any(part in {'path','root','directory','dir','file','command','cwd','pdf_browser'} for part in key.split('.')):raise ValueError('宿主路径与命令配置仅能在本机维护')


async def management(request,path):
    if path not in MANAGEMENT_PATHS:
        return JSONResponse({'ok':False,'error':'未开放的面板操作'},status_code=403,headers=NO_STORE)
    origin=str(request.url.replace(scheme='https',path='',query='',fragment='')).rstrip('/')
    if (request.headers.get('origin')!=origin or request.headers.get('x-panel')!='1'
            or request.headers.get('sec-fetch-site','same-origin')!='same-origin' or request.url.query):
        return JSONResponse({'ok':False,'error':'请从当前登录的面板操作'},status_code=403,headers=NO_STORE)
    if request.headers.get('content-type','').split(';',1)[0].strip().lower()!='application/json':
        return JSONResponse({'ok':False,'error':'请使用JSON提交'},status_code=415,headers=NO_STORE)
    raw=bytearray();limit=32*1024*1024 if path=='api/songs/upload' else 512*1024
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw)>limit:return JSONResponse({'ok':False,'error':'上传音频最大32MB；普通操作最大512KB'},status_code=413,headers=NO_STORE)
    try:
        body=json.loads(raw);validate_management(path,body)
    except (ValueError,TypeError,UnicodeError) as error:
        message=str(error) if type(error) is ValueError else '无效的JSON操作'
        return JSONResponse({'ok':False,'error':message[:120]},status_code=400,headers=NO_STORE)
    if needs_confirmation(path,body) and request.headers.get('x-panel-confirm')!='1':
        return JSONResponse({'ok':False,'error':'请在面板中确认此操作'},status_code=409,headers=NO_STORE)
    try:
        async with httpx.AsyncClient(timeout=180,trust_env=False,follow_redirects=False) as client:
            async with client.stream('POST','http://host.docker.internal:8765/'+path,json=body,
                    headers={'Host':'127.0.0.1:8765','X-Panel':'1'}) as response:
                result=bytearray()
                async for chunk in response.aiter_bytes():
                    result.extend(chunk)
                    if len(result)>8*1024*1024:raise ValueError('response too large')
                answer=json.loads(result)
                if not isinstance(answer,dict):raise ValueError('invalid response')
                return JSONResponse(answer,status_code=response.status_code,headers=NO_STORE)
    except (httpx.HTTPError,ValueError,UnicodeError):
        return JSONResponse({'ok':False,'error':'操作结果未能确认，请刷新查看状态后再决定是否重试'},status_code=503,headers=NO_STORE)


def remote_html(text):
    # The upstream app uses root-relative API/image links. Keep every request inside
    # this authenticated namespace, including JavaScript string/template literals.
    paths=r'''(["'`])/(?=api/|local-core(?:["'`?#])|sticker(?:thumb)?(?:["'`?/#])|qrcode(?:["'`?])|avatar(?:["'`?])|songclip(?:["'`?])|judge_eval(?:["'`?])|fuimg(?:["'`?])|voicefile(?:["'`?])|index\.html|#)'''
    text=re.sub(paths,lambda match:match.group(1)+PREFIX+'/',text)
    text=re.sub(r'''(href|src|action)=(['"])/\2''',lambda match:match.group(1)+'='+match.group(2)+PREFIX+'/'+match.group(2),text)
    qr='<img class="qr" src="/qq-panel/qrcode?t=${q.qr_t}" alt="登录二维码">'
    refresh='<div style="text-align:center">'+qr+'<button type="button" class="btn primary" data-qq-qr-refresh style="display:block;margin:10px auto">刷新二维码</button><div role="status" class="small" style="max-width:220px"></div></div>'
    text=text.replace(qr,refresh,1)
    text=text.replace('码每 2 分钟换一次，这里会自动换成最新的（扫了没反应就等它换新的再扫）','二维码过期或扫码没反应时，点击图片下方的“刷新二维码”，再扫描新图。')
    text=text.replace('只有这台电脑能打开','仅所有者可远程管理')
    text=text.replace('停止全部（会弹管理员确认）','停止聊天（保留QQ登录）').replace('启动全部（含 QQ）','启动聊天（保留QQ登录）')
    banner='<div style="padding:12px 20px;background:#e2f2f8;color:#12222b;border-bottom:1px solid #c4d5dc">远程管理 · 仅所有者账号可操作，删除数据和QQ登录需确认。<a href="/qq-panel/qq-login">QQ登录与连接诊断</a></div>'
    controls=REMOTE_CONTROLS
    return text.replace('<body>', '<body>'+banner,1).replace('</body>',controls+'</body>',1)



@router.get('/mac-mini/qq-panel')
@router.get('/mac-mini/qq-panel/{path:path}')
async def mac_entry(request:Request,path:str=''):
    destination=PREFIX+'/'+path
    if request.url.query:destination+='?'+request.url.query
    return RedirectResponse(destination,status_code=307)


@router.api_route('/qq-panel',methods=['GET','POST','PUT','PATCH','DELETE'])
async def root(request:Request):
    return await proxy(request,'')


@router.api_route('/qq-panel/{path:path}',methods=['GET','POST','PUT','PATCH','DELETE'])
async def proxy(request:Request,path:str):
    identity=getattr(request.state,'identity',None) or {}
    if str(identity.get('username','')).casefold()!='peyro-gogogo':
        return JSONResponse({'error':'仅图鉴所有者账号可查看机器人面板'},status_code=403,headers={'Cache-Control':'no-store'})
    if request.method!='GET':
        if request.method!='POST':return JSONResponse({'ok':False,'error':'仅允许GET/POST'},status_code=405,headers=NO_STORE)
        if path=='api/music/login':result=await netease_login(request)
        elif path=='api/send':result=await panel_send(request)
        else:result=await management(request,path)
        success=False
        try:success=json.loads(result.body).get('ok') is True
        except (ValueError,AttributeError):pass
        audit('qq_panel_operation',channel='auth',username=identity.get('username'),route=path,status=result.status_code,success=success)
        return result
    if path=='qq-login':return Response(QQ_LOGIN_HTML,media_type='text/html',headers=NO_STORE)
    if not path and not request.url.path.endswith('/'):
        return RedirectResponse(PREFIX+'/',status_code=307)
    if '..' in path or '\\' in path or path.startswith('/') or not re.fullmatch(r'[A-Za-z0-9_./-]*',path):
        return JSONResponse({'error':'无效路径'},status_code=400)
    try:
        async with httpx.AsyncClient(timeout=15,trust_env=False,follow_redirects=False) as client:
            async with client.stream('GET','http://host.docker.internal:8765/'+path,params=request.query_params,
                                     headers={'Host':'127.0.0.1:8765'}) as result:
                data=bytearray()
                async for chunk in result.aiter_bytes():
                    data.extend(chunk)
                    if len(data)>16*1024*1024:raise ValueError('panel response too large')
                content_type=result.headers.get('content-type','application/octet-stream')
                if 'text/html' in content_type:data=remote_html(data.decode('utf-8')).encode()
                return Response(bytes(data),status_code=result.status_code,headers={
                    'Content-Type':content_type,'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff',
                    'Referrer-Policy':'no-referrer','Content-Security-Policy':"frame-ancestors 'self'; base-uri 'self'"})
    except (httpx.HTTPError,ValueError):
        return JSONResponse({'error':'Mac机器人面板暂时不可用'},status_code=503,headers={'Cache-Control':'no-store'})
