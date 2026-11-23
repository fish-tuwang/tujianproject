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
    text=re.sub(r'''(["'`])/(?!/)''',lambda match:match.group(1)+PREFIX+'/',text)
    banner='<div style="padding:12px 20px;background:#e2f2f8;color:#12222b;border-bottom:1px solid #c4d5dc">异地只读查看 · 已通过图鉴账号鉴权；修改与管理请在 Mac 本机面板操作。</div>'
    return text.replace('<body>', '<body>'+banner,1)


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
