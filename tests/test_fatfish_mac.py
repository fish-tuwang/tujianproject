import asyncio
import io
import json
import tarfile
import time

import httpx
from fastapi.testclient import TestClient
from PIL import Image
import pytest

from qqbot.qq_bot import QQSettings, create_app
from qqbot import fatfish_mac
from scripts.mac_fatfish_update import extract
from official_qq.whale_tools import choose


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


@pytest.mark.parametrize('kind', ['image', 'record'])
def test_mac_media_uri_decodes_spaces_unicode_and_reserved_characters(tmp_path, monkeypatch, kind):
    import base64
    root=tmp_path/'Application Support'/'鲸鱼';root.mkdir(parents=True)
    monkeypatch.setattr(fatfish_mac,'ROOT',root)
    path=root/'睡觉 #1+100%25.png'
    Image.new('RGB',(4,4),'red').save(path)
    params={'message':[{'type':kind,'data':{'file':path.as_uri(),'summary':'保留元数据'}}]}
    result=fatfish_mac.rotate_images('10',params)
    data=result['message'][0]['data']
    assert base64.b64decode(data['file'].removeprefix('base64://'))==path.read_bytes()
    assert data['summary']=='保留元数据'
    assert params['message'][0]['data']['file']==path.as_uri()
    assert fatfish_mac.local_media_path(str(path))==path  # raw %25 must not be decoded


def test_missing_media_never_leaks_host_path_to_qq(tmp_path,monkeypatch):
    monkeypatch.setattr(fatfish_mac,'ROOT',tmp_path)
    with pytest.raises(ValueError,match='local_media_missing'):
        fatfish_mac.rotate_images('10',{'message':[{'type':'image','data':{'file':(tmp_path/'missing.png').as_uri()}}]})
    with pytest.raises(ValueError,match='remote_file_host'):
        fatfish_mac.local_media_path('file://remote-host/private.png')
    for value in ['https://example.com/a.png','base64://YWJj']:
        assert fatfish_mac.rotate_images('10',{'message':[{'type':'image','data':{'file':value}}]})['message'][0]['data']['file']==value
