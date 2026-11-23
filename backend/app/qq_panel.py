"""Owner-only remote viewing of the Mac FatFish panel using existing catalog auth."""
import re

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

router=APIRouter()
PREFIX='/qq-panel'


def remote_html(text):
    # The upstream app uses root-relative API/image links. Keep every request inside
    # this authenticated namespace, including JavaScript string/template literals.
    paths=r'''(["'`])/(?=api/|local-core(?:["'`?#])|sticker(?:thumb)?(?:["'`?/#])|qrcode(?:["'`?])|avatar(?:["'`?])|songclip(?:["'`?])|judge_eval(?:["'`?])|fuimg(?:["'`?])|voicefile(?:["'`?])|index\.html|#)'''
    text=re.sub(paths,lambda match:match.group(1)+PREFIX+'/',text)
    text=re.sub(r'''(href|src|action)=(['"])/\2''',lambda match:match.group(1)+'='+match.group(2)+PREFIX+'/'+match.group(2),text)
    text=text.replace('只有这台电脑能打开','通过图鉴账号异地只读查看')
    banner='<div style="padding:12px 20px;background:#e2f2f8;color:#12222b;border-bottom:1px solid #c4d5dc">异地只读查看 · 已通过图鉴账号登录；修改与管理请在 Mac 本机面板操作。</div>'
    readonly='''<script>(()=>{let pending=false;function disable(){pending=false;for(const b of document.querySelectorAll('main button,button[data-action]')){if(/^(启动机器人|重启机器人|停止机器人|强制重启|开火力|从现在重新算|回到平常|恢复平静|保存|添加|移入归档|删除|现在整理|关掉夜猫子|打开夜猫子|发送|代发|钉住|取消钉住|找回|现在忘)/.test(b.textContent.trim())){b.disabled=true;b.title='异地只读；请在Mac本机管理';}}}new MutationObserver(()=>{if(!pending){pending=true;requestAnimationFrame(disable);}}).observe(document.body,{childList:true,subtree:true});disable();})();</script>'''
    return text.replace('<body>', '<body>'+banner,1).replace('</body>',readonly+'</body>',1)


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
        return JSONResponse({'ok':False,'error':'异地面板为只读；请在Mac本机进行管理'},status_code=403)
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
