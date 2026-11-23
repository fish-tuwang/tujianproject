import asyncio
import io
import json
import tarfile
import time
from types import SimpleNamespace

import httpx
from fastapi.testclient import TestClient
from PIL import Image
import pytest

from qqbot.qq_bot import QQSettings, create_app
from qqbot import fatfish_mac
from scripts.mac_fatfish_update import extract
from official_qq.whale_tools import choose


@pytest.mark.parametrize('stderr,expected', [
    (b'HTTP Error 403: Forbidden','gateway_auth_failed'),
    (b'No such container: test','bridge_missing'),
    (b'Container test is not running','bridge_stopped'),
    (b'Cannot connect to the Docker daemon','docker_unavailable'),
    (b'private-token must not appear in errors','gateway_unavailable'),
])
def test_gateway_errors_are_categorized_without_private_details(monkeypatch,stderr,expected):
    monkeypatch.setattr(fatfish_mac.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=1,stdout=b'',stderr=stderr))
    with pytest.raises(RuntimeError,match='^'+expected+'$'):
        fatfish_mac.gateway({'operation':'action','action':'get_login_info'})


def test_gateway_missing_docker_and_invalid_response_are_explicit(monkeypatch):
    def missing(*a,**k):raise FileNotFoundError('private-path')
    monkeypatch.setattr(fatfish_mac.subprocess,'run',missing)
    with pytest.raises(RuntimeError,match='^docker_unavailable$'):fatfish_mac.gateway({})
    monkeypatch.setattr(fatfish_mac.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=0,stdout=b'private-output'))
    with pytest.raises(RuntimeError,match='^gateway_invalid_response$'):fatfish_mac.gateway({})


@pytest.mark.parametrize('online,expected', [(True,'ok'),(False,'offline'),(None,'error')])
def test_qq_status_checks_actual_connection_not_only_saved_identity(tmp_path,monkeypatch,online,expected):
    monkeypatch.setattr(fatfish_mac,'ROOT',tmp_path/'fatfish')
    def gateway(data):
        return {'retcode':0,'data':{'user_id':949494401} if data['action']=='get_login_info' else {'online':online}}
    monkeypatch.setattr(fatfish_mac,'gateway',gateway)
    assert fatfish_mac.qq_status(949494401)['state']==expected


def test_failed_probe_does_not_claim_qq_is_logging_in(monkeypatch):
    def failed(data):raise RuntimeError('gateway_auth_failed')
    monkeypatch.setattr(fatfish_mac,'gateway',failed)
    result=fatfish_mac.qq_status(949494401)
    assert result['state']=='error' and result['category']=='gateway_auth_failed'
    assert result['state'] not in {'starting','scan','offline'}


def test_old_login_required_state_is_not_reused(tmp_path,monkeypatch):
    monkeypatch.setattr(fatfish_mac,'ROOT',tmp_path/'fatfish')
    monkeypatch.setattr(fatfish_mac,'gateway',lambda data:{'retcode':0,'data':{'user_id':949494401} if data['action']=='get_login_info' else {'online':False}})
    file=tmp_path/'guard-state.json'
    file.write_text(json.dumps({'status':'login_required','checked_at':0}))
    assert fatfish_mac.qq_status(949494401)['state']=='offline'
    file.write_text(json.dumps({'status':'login_required','checked_at':time.time()}))
    assert fatfish_mac.qq_status(949494401)['state']=='scan'


def test_panel_diagnostic_is_read_only_and_keeps_local_host_check(monkeypatch):
    class Handler:
        path='/api/mac-qq-status'
        allowed=True
        def _host_ok(self):return self.allowed
        def _json(self,value,code=200):return value,code
        def do_GET(self):return {'native':True},200
        def route(self,path,body):return {'native':True}
        def _file(self,*args,**kwargs):pass
    panel=SimpleNamespace(H=Handler,cfg=lambda:{'bot_qq':949494401},serve=lambda **kwargs:None)
    monkeypatch.setattr(fatfish_mac,'load_module',lambda name:panel)
    monkeypatch.setattr(fatfish_mac,'qq_status',lambda account:{'state':'error','category':'bridge_stopped'})
    fatfish_mac.run_panel()
    handler=Handler()
    assert handler.do_GET()==({'state':'error','category':'bridge_stopped'},200)
    handler.allowed=False
    assert handler.do_GET()==({'ok':False},403)


def test_fatfish_uses_single_authenticated_gateway_and_enforces_scope(tmp_path):
    calls=[]
    def account(request):
        calls.append(request.url.path)
        return httpx.Response(200,json={'status':'ok','retcode':0,'data':{'user_id':949494401,'message_id':100}})
    settings=QQSettings(account='949494401',engine='fatfish',onebot_token='x'*40,llm_key='y'*40,allowed_groups='10',state_path=str(tmp_path/'bot.sqlite'),log_dir=str(tmp_path/'logs'))
    app=create_app(settings,account_transport=httpx.MockTransport(account))
    with TestClient(app,client=('127.0.0.1',1111)) as client:
        assert client.post('/admin/fatfish',json={'operation':'action','action':'get_login_info'}).status_code==403
        headers={'authorization':'Bearer '+'x'*40}
        assert client.post('/admin/fatfish',headers=headers,json={'operation':'action','action':'set_qq_profile'}).json()['retcode']==403
        assert client.post('/admin/fatfish',headers=headers,json={'operation':'action','action':'send_group_msg','params':{'group_id':11}}).json()['retcode']==403
        assert not calls
        assert client.post('/admin/fatfish',headers=headers,json={'operation':'action','action':'get_login_info'}).json()['retcode']==0
        assert client.post('/admin/fatfish',headers=headers,json={'operation':'idle_check','group':'10'}).json()['allowed'] is False
        import hmac
        event={'post_type':'message','message_type':'group','self_id':949494401,'user_id':12345,'group_id':10,'message_id':'abc','message':[{'type':'at','data':{'qq':'949494401'}},{'type':'text','data':{'text':'你好'}}]}
        body=json.dumps(event).encode();signature='sha1='+hmac.new(b'x'*40,body,'sha1').hexdigest()
        assert client.post('/onebot/events',content=body,headers={'x-signature':signature}).json()['engine']=='fatfish'
        assert client.post('/admin/fatfish',headers=headers,json={'operation':'poll'}).json()['event']['message_id']=='abc'
        assert app.state.queue.empty()  # the old Qwen worker must not also answer


def test_upstream_archive_rejects_links_and_traversal(tmp_path):
    for name,link in [('../config.json',False),('bot/config.json',True)]:
        output=io.BytesIO()
        with tarfile.open(fileobj=output,mode='w') as tar:
            info=tarfile.TarInfo(name)
            if link:info.type=tarfile.SYMTYPE;info.linkname='/etc/passwd'
            tar.addfile(info)
        with pytest.raises(ValueError):extract(output.getvalue(),tmp_path)


def test_picture_rotation_persists_and_strips_empty_quote(tmp_path,monkeypatch):
    monkeypatch.setattr(fatfish_mac,'ROOT',tmp_path)
    directory=tmp_path/'stickers';directory.mkdir()
    for name,color in [('sleep-a','red'),('sleep-b','blue')]:Image.new('RGB',(4,4),color).save(directory/(name+'.png'))
    (directory/'index.json').write_text(json.dumps({'stickers':{name:{'file':name+'.png','emo':'困'} for name in ['sleep-a','sleep-b']}}))
    params={'message':[{'type':'reply','data':{'id':'123'}},{'type':'text','data':{'text':''}},{'type':'image','data':{'file':str(directory/'sleep-a.png')}}]}
    first=fatfish_mac.rotate_images('10',params,remember=True)
    second=fatfish_mac.rotate_images('10',params,remember=True)
    third=fatfish_mac.rotate_images('10',params,remember=True)
    assert first['message'][0]['type']=='image'
    assert first['message'][0]['data']['file']!=second['message'][0]['data']['file']
    assert second['message'][0]['data']['file']!=third['message'][0]['data']['file']


def test_official_tool_rotates_independent_of_caption(tmp_path):
    directory=tmp_path/'stickers';directory.mkdir();entries=[]
    for name in ['a','b']:
        (directory/(name+'.png')).write_bytes(b'asset')
        entries.append({'id':name,'file':name+'.png','family':'sleep','fingerprint':name,'description':'DeepSleep'})
    (directory/'index.json').write_text(json.dumps({'entries':entries}))
    assert choose(tmp_path,'sleep')['id'] != choose(tmp_path,'sleep')['id']
