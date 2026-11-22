"""Poll GitHub main every five minutes and atomically update only the Mac QQ bridge."""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import plistlib
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import time

HOME=Path.home()
ROOT=HOME/'Library/Application Support/LittleAtlasQQ'
CATALOG_STATE=HOME/'Library/Application Support/LittleAtlasUpdater'
REPOSITORY='https://github.com/fish-tuwang/tujianproject.git'
LABEL='com.little-atlas.qq-updater'
IMAGE='little-atlas-mac-qq:20261121'
SUFFIXES={'.py','.json','.png','.jpg','.jpeg','.webp','.md'}
DOCKERFILE='''FROM little-atlas-mac-qq:runtime-base
RUN rm -rf /app/qqbot
COPY --chown=10001:10001 qqbot /app/qqbot
RUN python -m compileall -q /app/qqbot
USER 10001:10001
CMD ["python","-m","uvicorn","qqbot.qq_bot:application","--factory","--host","127.0.0.1","--port","8096","--no-access-log","--no-proxy-headers"]
'''


def log(message):
 print(time.strftime('%Y-%m-%d %H:%M:%S')+' '+message,flush=True)


def run(args,timeout=120,capture=True):
 process=subprocess.Popen(args,start_new_session=True,stdout=subprocess.PIPE if capture else None,stderr=subprocess.PIPE if capture else None)
 try:output,error=process.communicate(timeout=timeout)
 except subprocess.TimeoutExpired:
  try:os.killpg(process.pid,signal.SIGKILL)
  except ProcessLookupError:pass
  output,error=process.communicate()
  raise subprocess.TimeoutExpired(args,timeout,output=output,stderr=error)
 if process.returncode:raise subprocess.CalledProcessError(process.returncode,args,output=output,stderr=error)
 return output


@contextmanager
def locked(path):
 path.parent.mkdir(parents=True,exist_ok=True)
 with path.open('a') as handle:
  fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
  yield


def extract_package(body,directory):
 """Reject links, secrets, unexpected paths and oversized packages before writing."""
 if len(body)>32*1024*1024:raise ValueError('QQ source archive too large')
 files={}
 with tarfile.open(fileobj=io.BytesIO(body),mode='r:') as archive:
  members=archive.getmembers()
  for member in members:
   name=PurePosixPath(member.name)
   if name.is_absolute() or '..' in name.parts or not name.parts or name.parts[0]!='qqbot':raise ValueError('Unsafe QQ source path')
   if member.isdir():continue
   if not member.isfile() or name.suffix.lower() not in SUFFIXES or any(part.startswith('.') for part in name.parts):raise ValueError('Unsupported QQ source entry')
   if member.size>8*1024*1024:raise ValueError('QQ source file too large')
   data=archive.extractfile(member).read()
   files[str(name)]=data
 if not {'qqbot/__init__.py','qqbot/qq_bot.py','qqbot/qq_chat.py','qqbot/qq_images.py','qqbot/audit.py','qqbot/qq_stickers/index.json'}<=files.keys():raise ValueError('Incomplete Qwen bot package; current service kept')
 # Validate sticker assets so a code-only export cannot silently remove them.
 index=json.loads(files['qqbot/qq_stickers/index.json'])
 if not isinstance(index,dict) or not isinstance(index.get('entries'),list):raise ValueError('Invalid sticker index')
 for entry in index['entries']:
  filename=entry.get('file','')
  if not filename or PurePosixPath(filename).name!=filename or 'qqbot/qq_stickers/'+filename not in files:raise ValueError('Missing or unsafe sticker asset')
 for name,data in files.items():
  target=directory/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
 return {name:hashlib.sha256(data).hexdigest() for name,data in files.items()}


def health(name):
 code="import json,urllib.request; print(json.dumps(json.load(urllib.request.urlopen('http://127.0.0.1:8096/health/"+name+"',timeout=5))))"
 return json.loads(run(['docker','exec','little-atlas-mac-qq-bridge-1','python','-c',code],timeout=10))


def wait_healthy(require_online):
 deadline=time.monotonic()+60
 while time.monotonic()<deadline:
  try:
   if health('live').get('status')=='ok' and (not require_online or health('ready').get('status')=='ready'):return
  except (subprocess.SubprocessError,ValueError):pass
  time.sleep(2)
 raise RuntimeError('QQ bridge health check failed')


def compose(root,*args):
 run(['docker','compose','--env-file',str(root/'runtime.env'),'-f',str(root/'compose.yaml'),*args],timeout=120)


def deploy(root,target,archive):
 state=root/'updater';revision=state/'revision';old=run(['docker','inspect','little-atlas-mac-qq-bridge-1','--format','{{.Image}}']).decode().strip()
 try:online=health('ready').get('status')=='ready'
 except (subprocess.SubprocessError,ValueError):online=False
 new='little-atlas-mac-qq:auto-'+target[:12];switched=False
 with tempfile.TemporaryDirectory(prefix='stage-',dir=state) as directory:
  stage=Path(directory);hashes=extract_package(archive,stage);(stage/'Dockerfile').write_text(DOCKERFILE)
  log('BUILD_START '+target[:12]);run(['docker','build','--pull=false','-t',new,str(stage)],timeout=300)
  run(['docker','run','--rm','--entrypoint','python',new,'-c','import qqbot.qq_bot,qqbot.qq_chat,qqbot.qq_images'],timeout=30)
  try:
   run(['docker','image','tag',new,IMAGE]);switched=True
   compose(root,'up','-d','--no-deps','bridge');wait_healthy(online)
   code="import hashlib,json,sys;from pathlib import Path;d=json.loads(sys.argv[1]);assert all(hashlib.sha256((Path('/app')/n).read_bytes()).hexdigest()==h for n,h in d.items());print('FILES_VERIFIED',len(d))"
   run(['docker','exec','little-atlas-mac-qq-bridge-1','python','-c',code,json.dumps(hashes)],timeout=30)
  except BaseException:
   if switched:
    run(['docker','image','tag',old,IMAGE]);compose(root,'up','-d','--no-deps','bridge');wait_healthy(online);log('ROLLED_BACK QQ bridge; account and data volumes kept')
   raise
  history=state/'history';history.mkdir(exist_ok=True)
  # This reviewed host adapter is part of qqbot/, separate from upstream releases.
  # Never replace FatFish config.json, persona.md, data, account containers or credentials.
  adapter=root/'fatfish/adapter.py';source=stage/'qqbot/fatfish_mac.py'
  if adapter.is_file() and source.is_file() and adapter.read_bytes()!=source.read_bytes():
   backup=adapter.read_bytes();temp=adapter.with_suffix('.tmp');temp.write_bytes(source.read_bytes());temp.replace(adapter)
   try:
    for label in ['com.little-atlas.fatfish','com.little-atlas.fatfish-panel']:
     run(['launchctl','kickstart','-k','gui/'+str(os.getuid())+'/'+label],timeout=15)
   except BaseException:
    adapter.write_bytes(backup)
    for label in ['com.little-atlas.fatfish','com.little-atlas.fatfish-panel']:
     subprocess.run(['launchctl','kickstart','-k','gui/'+str(os.getuid())+'/'+label],capture_output=True)
    run(['docker','image','tag',old,IMAGE]);compose(root,'up','-d','--no-deps','bridge');wait_healthy(online)
    raise
  record={'revision':target,'previous_image':old,'image':new,'files':hashes,'online_before_update':online,'verified_at':time.time()}
  (history/(target+'.json')).write_text(json.dumps(record,indent=2))
  temp=revision.with_suffix('.tmp');temp.write_text(target+'\n');temp.replace(revision)
  log('QQ_UPDATE_OK '+target[:12]+' files='+str(len(hashes))+' account_container_unchanged=true')


def check(root):
 state=root/'updater';state.mkdir(parents=True,exist_ok=True,mode=0o700)
 try:
  with locked(state/'lock'),locked(CATALOG_STATE/'lock'):
   repo=CATALOG_STATE/'upstream.git'
   if not repo.is_dir():raise RuntimeError('Install the catalog updater first')
   git=['git','--git-dir='+str(repo)]
   log('FETCH_START GitHub main (90 second limit)')
   run(git+['-c','http.lowSpeedLimit=1024','-c','http.lowSpeedTime=20','fetch','--quiet',REPOSITORY,'main'],timeout=90)
   target=run(git+['rev-parse','FETCH_HEAD']).decode().strip();file=state/'revision';previous=file.read_text().strip() if file.exists() else ''
   if previous==target:log('QQ_UP_TO_DATE '+target[:12]);return
   if previous:
    run(git+['merge-base','--is-ancestor',previous,target])
    changes=run(git+['diff','--name-only',previous,target,'--','qqbot/']).decode().strip()
    if not changes:
     file.write_text(target+'\n');log('QQ_NO_CODE_CHANGES '+target[:12]);return
   archive=run(git+['archive','--format=tar',target,'qqbot/'])
   deploy(root,target,archive)
 except BlockingIOError:log('SKIP another catalog/QQ update is running; retry next interval')


def install(root):
 root=root.resolve()
 if not (root/'runtime.env').is_file() or not (root/'compose.yaml').is_file():raise RuntimeError('Migrate the QQ runtime first')
 script=root/'updater.py';shutil.copy2(__file__,script);script.chmod(0o700)
 agent=HOME/'Library/LaunchAgents'/ (LABEL+'.plist');agent.parent.mkdir(exist_ok=True,parents=True)
 path='/opt/homebrew/bin:/usr/local/bin:/Applications/Docker.app/Contents/Resources/bin:/usr/bin:/bin:/usr/sbin:/sbin'
 settings={'Label':LABEL,'ProgramArguments':[sys.executable,str(script),'--root',str(root)],'StartInterval':300,'RunAtLoad':True,'EnvironmentVariables':{'PATH':path,'GIT_TERMINAL_PROMPT':'0'},'StandardOutPath':str(root/'updater.log'),'StandardErrorPath':str(root/'updater-errors.log')}
 try:run(['docker','image','inspect','little-atlas-mac-qq:runtime-base'])
 except subprocess.CalledProcessError:run(['docker','image','tag',IMAGE,'little-atlas-mac-qq:runtime-base'])
 check(root)
 agent.write_bytes(plistlib.dumps(settings));subprocess.run(['launchctl','bootout','gui/'+str(os.getuid()),str(agent)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 run(['launchctl','bootstrap','gui/'+str(os.getuid()),str(agent)]);log('INSTALLED QQ updater; GitHub main every 300 seconds')


def main():
 parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=ROOT);parser.add_argument('--install',action='store_true');args=parser.parse_args()
 if args.install:install(args.root)
 else:check(args.root)

if __name__=='__main__':
 try:main()
 except Exception as error:
  # Errors never include environment values, model prompts or QQ message bodies.
  log('QQ_UPDATE_FAILED '+type(error).__name__+': '+str(error));sys.exit(1)
