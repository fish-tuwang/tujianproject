import io,json,tarfile,subprocess
from pathlib import Path
import pytest
from scripts import mac_qq_auto_update as updater


def archive(extra=None):
 files={n:b'# valid python\n' for n in ['qqbot/__init__.py','qqbot/qq_bot.py','qqbot/qq_chat.py','qqbot/qq_images.py','qqbot/audit.py']}
 files['qqbot/qq_stickers/index.json']=json.dumps({'entries':[]}).encode();files.update(extra or {})
 out=io.BytesIO()
 with tarfile.open(fileobj=out,mode='w') as tar:
  for name,body in files.items():
   info=tarfile.TarInfo(name);info.size=len(body);tar.addfile(info,io.BytesIO(body))
 return out.getvalue()


def test_package_rejects_parent_paths_and_missing_stickers_before_writing(tmp_path):
 with pytest.raises(ValueError,match='Unsafe'):
  updater.extract_package(archive({'qqbot/../../runtime.env':b'bad'}),tmp_path)
 assert not list(tmp_path.iterdir())
 with pytest.raises(ValueError,match='sticker'):
  updater.extract_package(archive({'qqbot/qq_stickers/index.json':b'{"entries":[{"file":"missing.png"}]}'}),tmp_path)
 assert not list(tmp_path.iterdir())


def test_failed_health_rolls_back_image_and_never_restarts_account(tmp_path,monkeypatch):
 (tmp_path/'updater').mkdir();calls=[];switches=[]
 def run(args,**kwargs):
  calls.append(args)
  return b'sha256:old\n' if args[:2]==['docker','inspect'] else b''
 def compose(root,*args):switches.append(args)
 attempts=[]
 def wait(online):
  attempts.append(online)
  if len(attempts)==1:raise RuntimeError('health failed')
 monkeypatch.setattr(updater,'run',run);monkeypatch.setattr(updater,'compose',compose)
 monkeypatch.setattr(updater,'health',lambda name:{'status':'ready'})
 monkeypatch.setattr(updater,'wait_healthy',wait)
 with pytest.raises(RuntimeError,match='health failed'):
  updater.deploy(tmp_path,'a'*40,archive())
 assert ['docker','image','tag','sha256:old',updater.IMAGE] in calls
 assert switches==[('up','-d','--no-deps','bridge')]*2
 assert not (tmp_path/'updater/revision').exists()


def test_success_records_revision_only_after_source_verification(tmp_path,monkeypatch):
 (tmp_path/'updater').mkdir();calls=[]
 def run(args,**kwargs):
  calls.append(args);return b'sha256:old\n' if args[:2]==['docker','inspect'] else b''
 monkeypatch.setattr(updater,'run',run);monkeypatch.setattr(updater,'compose',lambda *args:None)
 monkeypatch.setattr(updater,'health',lambda name:{'status':'ready'});monkeypatch.setattr(updater,'wait_healthy',lambda online:None)
 updater.deploy(tmp_path,'b'*40,archive())
 assert (tmp_path/'updater/revision').read_text().strip()=='b'*40
 assert any(args[:3]==['docker','exec','little-atlas-mac-qq-bridge-1'] for args in calls)


def test_network_command_timeout_is_bounded():
 import sys,time
 started=time.monotonic()
 with pytest.raises(subprocess.TimeoutExpired):
  updater.run([sys.executable,'-c','import time;time.sleep(10)'],timeout=.1)
 assert time.monotonic()-started<2
