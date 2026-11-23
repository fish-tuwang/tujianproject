"""Observe actual QQ state and perform bounded recovery using saved login only."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import time
import urllib.request

ROOT=Path.home()/'Library/Application Support/LittleAtlasQQ'
VERIFY=re.compile(r'登录态.*失效|登录态.*过期|安全验证|身份验证|人机|验证码|滑块|新设备验证|captcha|new.device|account.*blocked',re.I)


def _decide(state,observation,now):
 state={**state};state['checked_at']=now
 if (observation.get('stalled_transport') and observation.get('online')
     and not observation.get('requires_login') and observation.get('phase') not in {'qrcode_scanned','initializing','reconnecting'}):
  state['status']='transport_stalled'
  if state.get('offline_since') is None:state['offline_since']=now
  # A single failed send is insufficient; the caller requires repeated failures
  # over a minute. Without saved login a restart would merely require a QR.
  restarts=[t for t in state.get('restarts',[]) if 0<=now-t<3600]
  if observation.get('quick_eligible') is True and not state.get('requires_login') and not restarts:
   state.update(restarts=[now],next_retry=now+120);return state,'restart_account'
  return state,None
 if observation.get('online') and not observation.get('stalled_transport'):
  state.update(status='online',offline_since=None,attempts=[],next_retry=0,requires_login=False)
  return state,None
 if observation.get('probe_error'):
  state['status']='probe_error';return state,None
 if observation.get('requires_login'):
  state.update(status='login_required',requires_login=True);return state,None
 if observation.get('phase') in {'qrcode_scanned','initializing','reconnecting'}:
  state['status']='recovering';return state,None
 if state.get('requires_login'):
  state.update(status='login_required',requires_login=True);return state,None
 if state.get('offline_since') is None:state['offline_since']=now
 state['status']='offline'
 if now-state['offline_since']<60:return state,None
 if observation.get('phase') in {'qrcode_scanned','initializing','reconnecting'}:
  state['status']='recovering';return state,None
 if observation.get('account_stopped'):
  attempts=[t for t in state.get('starts',[]) if now-t<3600]
  if not attempts:state.update(starts=[now],status='starting_account');return state,'start_account'
  return state,None
 if not observation.get('quick_eligible'):
  state.update(status='login_required',requires_login=True);return state,None
 attempts=[t for t in state.get('attempts',[]) if now-t<3600]
 restarts=[t for t in state.get('restarts',[]) if now-t<3600]
 if len(attempts)>=2 and now-state['offline_since']>=300 and state.get('last_action_error')=='stale_login_state' and not restarts:
  state.update(restarts=[now],status='restarting_stale_client',next_retry=now+120);return state,'restart_account'
 requests=[t for t in state.get('recovery_requests',[]) if 0<=now-t<3600]
 if len(attempts)>=3 or len(requests)>=3:
  state['status']='rate_limited';return state,None
 if now<state.get('next_retry',0):return state,None
 state['recovery_requests']=requests+[now]
 state.update(attempts=attempts+[now],next_retry=now+[60,300,900][len(attempts)],status='quick_login_requested')
 return state,'quick_login'


def decide(state,observation,now):
 previous=state.get('status');since=state.get('offline_since')
 updated,action=_decide(state,observation,now)
 updated['reason']=observation.get('reason') or ('probe_failed' if observation.get('probe_error') else
                    'online' if observation.get('online') else 'verification_required' if observation.get('requires_login') else
                    'account_stopped' if observation.get('account_stopped') else 'qq_offline')
 if updated['status']=='login_required' and not observation.get('requires_login'):
  updated['reason']='saved_login_unavailable' if observation.get('quick_eligible') is False else 'verification_required'
 if 'quick_eligible' in observation:updated['quick_login_eligible']=observation['quick_eligible']
 if observation.get('online') and not observation.get('stalled_transport'):
  updated['last_online_at']=now
  if since is not None:updated['last_outage']={'started_at':since,'recovered_at':now,'seconds':max(0,now-since)}
 if previous!=updated['status'] or not state.get('history'):
  history=list(state.get('history',[]))
  history.append({'at':now,'from':previous,'to':updated['status'],'reason':updated['reason']})
  updated['history']=history[-40:]
 return updated,action


class WebUI:
 def __init__(self,root):
  self.token=json.loads((root/'backup/qq/config/webui.json').read_text())['token'];self.credential=None
 def post(self,path,body=None):
  headers={'Content-Type':'application/json'}
  if self.credential:headers['Authorization']='Bearer '+self.credential
  request=urllib.request.Request('http://127.0.0.1:6099/api'+path,json.dumps(body or {}).encode(),headers,method='POST')
  with urllib.request.urlopen(request,timeout=8) as response:result=json.load(response)
  if result.get('code')!=0:
   # Classify verification errors without persisting raw URLs or login details.
   message=str(result.get('message',''))
   category='verification_required' if VERIFY.search(message) else 'stale_login_state' if 'qq is logined' in message.lower() else 'quick_login_rejected'
   error=RuntimeError(category)
   raise error
  return result.get('data')
 def auth(self):
  self.credential=self.post('/auth/login',{'hash':hashlib.sha256((self.token+'.napcat').encode()).hexdigest()})['Credential']


def command(args):
 return subprocess.run(args,check=True,capture_output=True,text=True,timeout=30).stdout


def inspect_account():
 return json.loads(command(['docker','inspect','little-atlas-mac-qq-account-1']))[0]['State']


def observe(api,account):
 status=api.post('/QQLogin/CheckLoginStatus') or {}
 quick=None
 try:
  saved=api.post('/QQLogin/GetQuickLoginListNew') or []
  quick=any(str(r.get('uin'))==account and r.get('isQuickLogin') for r in saved)
 except Exception:pass  # A saved-login query failure cannot turn an online account offline.
 if status.get('isLogin') and status.get('coreReady') and status.get('isOffline') is not True:
  identity=api.post('/QQLogin/GetQQLoginInfo') or {}
  if str(identity.get('uin'))!=account:return {'requires_login':True,'reason':'account_mismatch'}
  return {'online':True,'quick_eligible':quick}
 if quick is None:return {'probe_error':True,'reason':'saved_login_probe_failed'}
 return {'phase':status.get('loginPhase'),'requires_login':bool(VERIFY.search(str(status.get('loginError','')))),
         'quick_eligible':quick}


def transport_observation(root,observation,now):
 if not observation.get('online'):return observation
 try:
  d=json.loads((root/'fatfish/delivery-state.json').read_text())
  stalled=(d.get('category')=='qq_network_error' and d.get('consecutive_network_failures',0)>=3
           and 0<=now-d.get('checked_at',0)<300 and d.get('checked_at',0)-d.get('network_failure_since',now)>=60)
  if stalled:return {**observation,'stalled_transport':True,'reason':'repeated_send_network_failure'}
 except (OSError,ValueError,TypeError):pass
 return observation


def reset_transport_evidence(root,before):
 path=root/'fatfish/delivery-state.json'
 try:
  with path.with_suffix('.json.lock').open('a') as lock:
   fcntl.flock(lock,fcntl.LOCK_EX)
   d=json.loads(path.read_text())
   if d.get('checked_at',0)<=before:
    d['consecutive_network_failures']=0
    temp=path.with_suffix('.reset.tmp');temp.write_text(json.dumps(d));temp.chmod(0o600);temp.replace(path)
 except (OSError,ValueError,TypeError):pass


def tick(root,configure=False):
 root.mkdir(parents=True,exist_ok=True,mode=0o700)
 with (root/'guard.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  with (root/'updater/lock').open('a') as updating:
   fcntl.flock(updating,fcntl.LOCK_EX|fcntl.LOCK_NB)
   file=root/'guard-state.json';state=json.loads(file.read_text()) if file.exists() else {}
   env={l.split('=',1)[0]:l.split('=',1)[1] for l in (root/'runtime.env').read_text().splitlines() if '=' in l and not l.startswith('#')};account=env['QQ_ACCOUNT']
   api=WebUI(root)
   try:
    container=inspect_account()
    if not container['Running']:observation={'account_stopped':True}
    else:
     api.auth()
     if configure:
      api.post('/QQLogin/SetQuickLoginQQ',{'uin':account})
      if str(api.post('/QQLogin/GetQuickLoginQQ'))!=account:raise RuntimeError('auto_login_configuration_not_saved')
     observation=transport_observation(root,observe(api,account),time.time())
   except Exception:
    if configure:raise
    observation={'probe_error':True}
   previous=state.get('status');state,action=decide(state,observation,time.time())
   if action:
    try:
     if action=='quick_login':api.post('/QQLogin/SetQuickLogin',{'uin':account})
     elif action=='start_account':command(['docker','compose','--env-file',str(root/'runtime.env'),'-f',str(root/'compose.yaml'),'up','-d','account'])
     elif action=='restart_account':
      before=time.time();command(['docker','restart','--time','20','little-atlas-mac-qq-account-1']);reset_transport_evidence(root,before)
     state.pop('last_action_error',None)
     state['last_action']=action;state['last_action_at']=time.time()
    except Exception as error:
     state['last_action_error']=str(error) if str(error) in {'verification_required','quick_login_rejected','stale_login_state'} else type(error).__name__
     if state['last_action_error']=='verification_required':state.update(status='login_required',requires_login=True)
   if state.get('status')!=previous or action:print(time.strftime('%Y-%m-%d %H:%M:%S'),'QQ_GUARD',state['status'],action or '',flush=True)
   temp=file.with_suffix('.tmp');temp.write_text(json.dumps(state,indent=2)+'\n');temp.chmod(0o600);temp.replace(file)
   return state


def install(root):
 tick(root,configure=True)
 destination=root/'guard.py';shutil.copy2(__file__,destination);destination.chmod(0o700)
 label='com.little-atlas.qq-guard';agent=Path.home()/'Library/LaunchAgents'/(label+'.plist')
 data={'Label':label,'ProgramArguments':[sys.executable,str(destination),'--root',str(root)],'RunAtLoad':True,'StartInterval':30,'EnvironmentVariables':{'PATH':'/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin'},'StandardOutPath':str(root/'guard.log'),'StandardErrorPath':str(root/'guard-errors.log')}
 agent.write_bytes(plistlib.dumps(data));subprocess.run(['launchctl','bootout','gui/'+str(os.getuid()),str(agent)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);command(['launchctl','bootstrap','gui/'+str(os.getuid()),str(agent)])
 print('QQ_GUARD_INSTALLED interval=30 quick_login=bounded saved_account_only=true')


def main():
 parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=ROOT);parser.add_argument('--install',action='store_true');args=parser.parse_args()
 if args.install:install(args.root)
 else:tick(args.root)

if __name__=='__main__':
 try:main()
 except BlockingIOError:pass
 except Exception as error:
  print('QQ_GUARD_FAILED',type(error).__name__,flush=True);sys.exit(1)
