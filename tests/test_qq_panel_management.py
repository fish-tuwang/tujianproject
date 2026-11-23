import json
import httpx
import pytest
from fastapi.testclient import TestClient
from backend.app import qq_panel
from tests.test_qq_panel_send import app,HEADERS


@pytest.fixture
def forwarded(monkeypatch):
    calls=[]
    class Response:
        status_code=200
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def aiter_bytes(self):yield b'{"ok":true}'
    class Client:
        def __init__(self,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        def stream(self,method,url,**kwargs):calls.append((method,url,kwargs));return Response()
    monkeypatch.setattr(qq_panel.httpx,'AsyncClient',Client)
    return calls


@pytest.mark.parametrize('path,body',[
    ('api/config',{'changes':[{'path':'behavior.group_reply_prob','value':.1}]}),
    ('api/persona',{'text':'温和诚实的性格'*20}),
    ('api/memory/add',{'key':'group_12345','text':'明确事实'}),
    ('api/local-core',{'action':'reset_mood'}),
    ('api/stickers/toggle',{'name':'sleep','off':False}),
    ('api/songs/save',{'id':'a','name':'歌名'}),
    ('api/music/login',{'platform':'qq','action':'check'}),
    ('api/music/login',{'platform':'kugou','action':'poll'}),
])
def test_owner_can_manage_all_normal_sections(path,body,forwarded):
    with TestClient(app()) as client:
        response=client.post('/qq-panel/'+path,headers=HEADERS,json=body)
        assert response.status_code==200 and response.json()['ok']
    assert len(forwarded)==1
    assert set(forwarded[0][2]['headers'])=={'Host','X-Panel'}


@pytest.mark.parametrize('path,body',[
    ('api/wipe',{'uid':'12345'}),('api/memory/forget',{'key':'group_12345','id':'a'}),
    ('api/songs/delete',{'id':'song'}),('api/bot',{'action':'shutdown'}),
    ('api/music/login',{'platform':'netease','action':'logout'}),
    ('api/mac-qq-login',{'action':'refresh'}),
])
def test_sensitive_operations_require_confirmation(path,body,forwarded):
    with TestClient(app()) as client:
        assert client.post('/qq-panel/'+path,headers=HEADERS,json=body).status_code==409
        assert not forwarded
        response=client.post('/qq-panel/'+path,headers={**HEADERS,'X-Panel-Confirm':'1'},json=body)
        assert response.status_code==200 and response.json()['ok']
    assert len(forwarded)==1


@pytest.mark.parametrize('path,body',[
    ('api/tool',{'name':'install_voice'}),('api/unknown',{}),
    ('api/config',{'changes':[{'path':'panel.token','value':'bad'}]}),
    ('api/config',{'changes':[{'path':'onebot.url','value':'http://evil'}]}),
    ('api/config',{'changes':[{'path':'make.pdf_browser','value':'evil'}]}),
    ('api/config',{'changes':[{'path':'persona_file','value':'../../outside'}]}),
])
def test_unknown_and_host_security_operations_not_forwarded(path,body,forwarded):
    with TestClient(app()) as client:
        assert client.post('/qq-panel/'+path,headers=HEADERS,json=body).status_code in {400,403}
    assert not forwarded


def test_other_accounts_and_cross_origin_are_denied(forwarded):
    with TestClient(app()) as client:
        for headers in [{**HEADERS,'x-test-user':'other'},{**HEADERS,'origin':'https://evil.test'}]:
            assert client.post('/qq-panel/api/local-core',headers=headers,json={'action':'reset_mood'}).status_code==403
    assert not forwarded


def test_qq_login_page_is_owner_only():
    with TestClient(app()) as client:
        assert client.get('/qq-panel/qq-login').status_code==403
        result=client.get('/qq-panel/qq-login',headers=HEADERS)
        assert result.status_code==200 and 'QQ登录与连接诊断' in result.text
