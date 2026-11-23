import base64
from types import SimpleNamespace
from qqbot import fatfish_mac


def setup_guard(tmp_path,monkeypatch,status):
    root=tmp_path/'fatfish';root.mkdir()
    monkeypatch.setattr(fatfish_mac,'ROOT',root)
    text='''import re
VERIFY=re.compile('需要安全验证')
class WebUI:
 def __init__(self,root):pass
 def auth(self):pass
 def post(self,path,body=None):
  if path.endswith('CheckLoginStatus'):return STATUS
  if path.endswith('RefreshQRcode'):return {}
  raise AssertionError('unexpected action')
'''.replace('STATUS',repr(status))
    (tmp_path/'guard.py').write_text(text)
    return root


def test_qr_refresh_does_nothing_when_online(tmp_path,monkeypatch):
    setup_guard(tmp_path,monkeypatch,{'isLogin':True,'coreReady':True})
    monkeypatch.setattr(fatfish_mac.subprocess,'run',lambda *a,**k:(_ for _ in ()).throw(AssertionError('must not call Docker')))
    result=fatfish_mac.refresh_login_qr()
    assert result['ok'] and 'img' not in result


def test_qr_refresh_waits_for_a_new_image_and_never_restarts(tmp_path,monkeypatch):
    root=setup_guard(tmp_path,monkeypatch,{'isLogin':False,'loginPhase':'waiting_qrcode'})
    old=b'\x89PNG\r\n\x1a\nold';new=b'\x89PNG\r\n\x1a\nnew';responses=iter([old,old,new]);calls=[]
    def run(args,**kwargs):calls.append(args);return SimpleNamespace(returncode=0,stdout=next(responses))
    monkeypatch.setattr(fatfish_mac.subprocess,'run',run);monkeypatch.setattr(fatfish_mac.time,'sleep',lambda _:None)
    result=fatfish_mac.refresh_login_qr()
    assert result['ok'] and base64.b64decode(result['img'].split(',',1)[1])==new
    assert (root.parent/'login-qr.png').read_bytes()==new
    assert all(args[:3]==['docker','exec','little-atlas-mac-qq-account-1'] for args in calls)


def test_qr_refresh_preserves_confirmation_in_progress(tmp_path,monkeypatch):
    setup_guard(tmp_path,monkeypatch,{'isLogin':False,'loginPhase':'qrcode_scanned'})
    monkeypatch.setattr(fatfish_mac.subprocess,'run',lambda *a,**k:(_ for _ in ()).throw(AssertionError('must not call Docker')))
    assert not fatfish_mac.refresh_login_qr()['ok']
