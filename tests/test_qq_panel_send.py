import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app import qq_panel
from scripts.configure_panel_post_proxy import render_config


def app():
    result=FastAPI();result.include_router(qq_panel.router)
    @result.middleware('http')
    async def identity(request,next):
        request.state.identity={'username':request.headers.get('x-test-user','')};return await next(request)
    return result


HEADERS={'x-test-user':'peyro-gogogo','origin':'https://testserver','x-panel':'1','sec-fetch-site':'same-origin'}
BODY={'scene':'group','target':'12345','text':'','sticker':'sleep-pa-zhe-shui-jiao','voice':False,'emo':'','remember':False}


def test_owner_can_send_only_sticker_without_forwarding_catalog_cookie(monkeypatch):
    calls=[]
    class Client:
        def __init__(self,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def post(self,url,**kwargs):
            calls.append((url,kwargs));return httpx.Response(200,json={'ok':True,'error':''},request=httpx.Request('POST',url))
    monkeypatch.setattr(qq_panel.httpx,'AsyncClient',Client)
    with TestClient(app()) as client:
        response=client.post('/qq-panel/api/send',headers={**HEADERS,'Cookie':'catalog_session=private'},json=BODY)
        assert response.status_code==200 and response.json()['ok']
    assert calls[0][1]['json']['text']=='' and calls[0][1]['json']['sticker']==BODY['sticker']
    assert set(calls[0][1]['headers'])=={'Host','X-Panel'}


@pytest.mark.parametrize('headers,body,status',[
    ({},BODY,403),
    ({**HEADERS,'x-test-user':'other'},BODY,403),
    ({**HEADERS,'origin':'https://evil.test'},BODY,403),
    ({**HEADERS,'sec-fetch-site':'cross-site'},BODY,403),
    (HEADERS,{**BODY,'text':'','sticker':''},400),
    (HEADERS,{**BODY,'target':'https://evil.test'},400),
    (HEADERS,{**BODY,'action':'restart'},400),
])
def test_send_rejects_wrong_user_csrf_or_payload(headers,body,status):
    with TestClient(app()) as client:
        assert client.post('/qq-panel/api/send',headers=headers,json=body).status_code==status


def test_ui_allows_send_but_keeps_other_management_protected():
    page=qq_panel.remote_html('<body><main><button id="go">发送</button></main></body>')
    assert "window.fetch=async" in page
    assert '仅所有者账号可操作' in page
    with TestClient(app()) as client:
        assert client.post('/qq-panel/api/bot',headers=HEADERS,json={'action':'restart'}).status_code==409


def test_nginx_changes_are_scoped_and_keep_mac_relay_target():
    original='''http { server { listen 443 ssl;
        location / { proxy_pass $atlas_mac_upstream; }
    }}'''
    result=render_config(original)
    assert 'location ^~ /qq-panel/api/ {' in result
    assert 'client_max_body_size 32m;' in result
    assert result.count('limit_except GET HEAD POST { deny all; }')==1
    assert result.count('proxy_pass $atlas_mac_upstream;')==2
    assert render_config(result)==result
