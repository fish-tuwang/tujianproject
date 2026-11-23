"""Owner-only Mac panel proxy with a scoped NetEase QR-login exception."""
import json
import re

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

router=APIRouter()
PREFIX='/qq-panel'
NO_STORE={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer'}


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
    if (not isinstance(body,dict) or set(body)!={'platform','action'} or body.get('platform')!='netease'
            or body.get('action') not in ('start','poll','check') or request.url.query):
        return JSONResponse({'ok':False,'error':'仅允许网易云扫码关联与登录检查'},status_code=403,headers=NO_STORE)
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
            if not isinstance(img,str) or not re.fullmatch(r'data:image/png;base64,[A-Za-z0-9+/=\r\n]+',img):
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


def remote_html(text):
    # The upstream app uses root-relative API/image links. Keep every request inside
    # this authenticated namespace, including JavaScript string/template literals.
    paths=r'''(["'`])/(?=api/|local-core(?:["'`?#])|sticker(?:thumb)?(?:["'`?/#])|qrcode(?:["'`?])|avatar(?:["'`?])|songclip(?:["'`?])|judge_eval(?:["'`?])|fuimg(?:["'`?])|voicefile(?:["'`?])|index\.html|#)'''
    text=re.sub(paths,lambda match:match.group(1)+PREFIX+'/',text)
    text=re.sub(r'''(href|src|action)=(['"])/\2''',lambda match:match.group(1)+'='+match.group(2)+PREFIX+'/'+match.group(2),text)
    text=text.replace('只有这台电脑能打开','通过图鉴账号异地只读查看')
    banner='<div style="padding:12px 20px;background:#e2f2f8;color:#12222b;border-bottom:1px solid #c4d5dc">所有者面板 · 支持代发文字/表情及扫码关联网易云；其他管理操作仍为只读。登录信息仅保存在家庭 Mac。</div>'
    readonly='''<script>(()=>{let pending=false;function disable(){pending=false;for(const b of document.querySelectorAll('main button,button[data-action]')){if(b.id==='go')continue;if(/^(启动机器人|重启机器人|停止机器人|强制重启|开火力|从现在重新算|回到平常|恢复平静|保存|添加|移入归档|删除|现在整理|关掉夜猫子|打开夜猫子|发送|代发|钉住|取消钉住|找回|现在忘)/.test(b.textContent.trim())){b.disabled=true;b.title='异地只读；请在Mac本机管理';}}}new MutationObserver(()=>{if(!pending){pending=true;requestAnimationFrame(disable);}}).observe(document.body,{childList:true,subtree:true});disable();})();</script>'''
    music='''<script>(()=>{let pending=false;function restrictMusic(){pending=false;for(const b of document.querySelectorAll('[data-mu]')){const a=b.dataset.mu,p=b.dataset.pf;if(a==='cancel'||(p==='netease'&&['start','check'].includes(a)))continue;b.disabled=true;b.title='远程仅允许网易云扫码关联；其他操作请在Mac本机进行';}}new MutationObserver(()=>{if(!pending){pending=true;requestAnimationFrame(restrictMusic);}}).observe(document.body,{childList:true,subtree:true});restrictMusic();})();</script>'''
    return text.replace('<body>', '<body>'+banner,1).replace('</body>',readonly+music+'</body>',1)


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
        if request.method=='POST' and path=='api/music/login':
            return await netease_login(request)
        if request.method=='POST' and path=='api/send':
            return await panel_send(request)
        return JSONResponse({'ok':False,'error':'异地面板为只读；请在Mac本机进行管理'},status_code=403,headers=NO_STORE)
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
