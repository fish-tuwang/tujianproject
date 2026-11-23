import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app.qq_panel import router,remote_html


def test_remote_panel_denies_other_users_and_all_mutations():
    app=FastAPI();app.include_router(router)
    @app.middleware('http')
    async def identity(request,next):
        request.state.identity={'username':request.headers.get('x-test-user','')}
        return await next(request)
    with TestClient(app) as client:
        assert client.get('/qq-panel/api/local-core').status_code==403
        assert client.get('/qq-panel/api/local-core',headers={'x-test-user':'other'}).status_code==403
        assert client.post('/qq-panel/api/local-core',headers={'x-test-user':'peyro-gogogo'},json={'action':'reset_mood'}).status_code==403


def test_all_native_root_links_stay_authenticated():
    page=remote_html('''<body><a href="/local-core">管理</a><img src="/sticker?f=a"><script>fetch('/api/overview');const x=`/api/local-core`;const y='https://example.com';</script>''')
    assert 'href="/qq-panel/local-core"' in page
    assert "fetch('/qq-panel/api/overview')" in page
    assert '`/qq-panel/api/local-core`' in page
    assert 'https://example.com' in page and '异地只读查看' in page
    assert "'/100分'" in remote_html("<script>const denominator='/100分';</script>")
    assert 'href="/qq-panel/"' in remote_html('<a href="/">返回</a>')
    assert '"/"+3' in remote_html('<script>const ratio="/"+3;</script>')


def test_mac_entry_resolves_to_authenticated_namespace():
    app=FastAPI();app.include_router(router)
    with TestClient(app) as client:
        response=client.get('/mac-mini/qq-panel/local-core',follow_redirects=False)
        assert response.status_code==307
        assert response.headers['location']=='/qq-panel/local-core'


def music_client(monkeypatch, handler):
    real_client=httpx.AsyncClient
    monkeypatch.setattr('backend.app.qq_panel.httpx.AsyncClient',
                        lambda **kwargs: real_client(**kwargs,transport=httpx.MockTransport(handler)))
    app=FastAPI();app.include_router(router)
    @app.middleware('http')
    async def identity(request,next):
        request.state.identity={'username':request.headers.get('x-test-user','')}
        return await next(request)
    return TestClient(app,base_url='https://panel.example',headers={
        'X-Test-User':'peyro-gogogo','Origin':'https://panel.example','X-Panel':'1'})


@pytest.mark.parametrize('action', ['start','poll','check'])
def test_netease_login_only_forwards_scoped_body_and_sanitized_result(monkeypatch,action):
    calls=[]
    def upstream(request):
        calls.append(request)
        assert request.url==httpx.URL('http://host.docker.internal:8765/api/music/login')
        assert request.method=='POST' and json.loads(request.content)=={'platform':'netease','action':action}
        assert request.headers['host']=='127.0.0.1:8765' and request.headers['x-panel']=='1'
        assert 'cookie' not in request.headers and 'authorization' not in request.headers
        return httpx.Response(200,json={'ok':True,'state':'ok','img':'data:image/png;base64,iVBORw0KGgo=',
            'nick':'owner','valid':None,'asked':False,'vip':True,'key':'private-qr-key',
            'cookies':{'MUSIC_U':'private-cookie'},'extra':{'token':'private-token'}},
            headers={'Set-Cookie':'MUSIC_U=private-cookie'})
    with music_client(monkeypatch,upstream) as client:
        response=client.post('/qq-panel/api/music/login',json={'platform':'netease','action':action},
                             headers={'Cookie':'catalog_auth=private-catalog-session'})
    assert response.status_code==200 and response.json()['ok']
    assert len(calls)==1 and response.json()['valid'] is None
    assert ('img' in response.json())==(action=='start')
    assert 'private-' not in response.text and 'set-cookie' not in response.headers
    assert 'no-store' in response.headers['cache-control']


@pytest.mark.parametrize('body', [
    {'platform':'qq','action':'start'}, {'platform':'kugou','action':'poll'},
    {'platform':'netease','action':'logout'}, {'platform':'netease','action':'start','cookie':'secret'},
    {'platform':'netease','action':'start','url':'http://evil.example'}, [], None,
])
def test_remote_music_rejects_other_platforms_actions_and_extra_fields(monkeypatch,body):
    def upstream(request):
        pytest.fail('denied request reached upstream')
    with music_client(monkeypatch,upstream) as client:
        response=client.post('/qq-panel/api/music/login',content=json.dumps(body),headers={'Content-Type':'application/json'})
    assert response.status_code==403


@pytest.mark.parametrize('headers', [
    {'Origin':'https://evil.example'}, {'Origin':'null'}, {'Origin':''}, {'X-Panel':''},
    {'Sec-Fetch-Site':'cross-site'}, {'X-Test-User':'other'}, {'X-Test-User':''},
])
def test_netease_login_keeps_owner_and_csrf_checks(monkeypatch,headers):
    def upstream(request):
        pytest.fail('unauthorized request reached upstream')
    with music_client(monkeypatch,upstream) as client:
        response=client.post('/qq-panel/api/music/login',json={'platform':'netease','action':'start'},headers=headers)
    assert response.status_code==403 and 'no-store' in response.headers['cache-control']


@pytest.mark.parametrize('path,method,content,content_type,expected', [
    ('api/music/login','POST',b'{','application/json',400),
    ('api/music/login','POST',b'x'*1025,'application/json',413),
    ('api/music/login','POST',b'{}','text/plain',415),
    ('api/music/login?token=secret','POST',b'{"platform":"netease","action":"poll"}','application/json',403),
    ('api/music/login','PUT',b'{}','application/json',403),
    ('api/config','POST',b'{}','application/json',403),
    ('api/bot','POST',b'{"action":"restart"}','application/json',403),
])
def test_music_exception_does_not_open_other_remote_writes(monkeypatch,path,method,content,content_type,expected):
    def upstream(request):
        pytest.fail('invalid request reached upstream')
    with music_client(monkeypatch,upstream) as client:
        response=client.request(method,'/qq-panel/'+path,content=content,headers={'Content-Type':content_type})
    assert response.status_code==expected


@pytest.mark.parametrize('kind', ['timeout','redirect','invalid_json','bad_image','oversize'])
def test_failed_login_does_not_echo_private_upstream_details(monkeypatch,kind):
    def upstream(request):
        if kind=='timeout':raise httpx.ReadTimeout('private-cookie',request=request)
        if kind=='redirect':return httpx.Response(302,headers={'Location':'https://evil.example/private-cookie'})
        if kind=='invalid_json':return httpx.Response(200,text='private-cookie')
        if kind=='oversize':return httpx.Response(200,content=b'x'*(512*1024+1))
        return httpx.Response(200,json={'ok':True,'img':'https://evil.example/private-cookie'})
    with music_client(monkeypatch,upstream) as client:
        response=client.post('/qq-panel/api/music/login',json={'platform':'netease','action':'start'})
    assert response.status_code==503 and response.json()['ok'] is False
    assert 'private-cookie' not in response.text and 'no-store' in response.headers['cache-control']


def test_remote_ui_explains_exception_and_disables_other_music_controls():
    page=remote_html('<body><button data-mu="start" data-pf="netease">扫码登录</button></body>')
    assert '仅所有者可扫码关联网易云' in page and '登录信息仅保存在家庭 Mac' in page
    assert "p==='netease'&&['start','check'].includes(a)" in page
    assert "a==='cancel'" in page and 'b.disabled=true' in page


def test_tls_termination_keeps_https_origin_check(monkeypatch):
    def upstream(request):
        return httpx.Response(200,json={'ok':True,'state':'wait'})
    with music_client(monkeypatch,upstream) as client:
        response=client.post('http://panel.example/qq-panel/api/music/login',json={'platform':'netease','action':'poll'})
        assert response.status_code==200
        response=client.post('http://panel.example/qq-panel/api/music/login',
            json={'platform':'netease','action':'poll'},headers={'Origin':'http://panel.example','X-Forwarded-Proto':'https'})
        assert response.status_code==403
