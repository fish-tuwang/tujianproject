from scripts.mac_qq_guard import decide,VERIFY


def test_probe_failures_never_trigger_login_or_restart():
 state,action=decide({}, {'probe_error':True},100)
 assert action is None and state['status']=='probe_error'


def test_real_offline_needs_grace_then_backoff_and_hourly_limit():
 obs={'quick_eligible':True,'phase':'offline'}
 state,action=decide({},obs,100);assert action is None
 state,action=decide(state,obs,161);assert action=='quick_login'
 state,action=decide(state,obs,180);assert action is None
 state,action=decide(state,obs,222);assert action=='quick_login'
 state,action=decide(state,obs,523);assert action=='quick_login'
 state,action=decide(state,obs,2000);assert action is None


def test_verification_never_attempts_saved_login():
 state,action=decide({'offline_since':0},{'requires_login':True,'quick_eligible':True},100)
 assert action is None and state['requires_login']
 assert VERIFY.search('快速登录态已失效，请重新登录')
 assert not VERIFY.search('二维码已过期，请刷新')


def test_reconnecting_and_scanning_are_left_alone():
 for phase in ['reconnecting','initializing','qrcode_scanned']:
  _,action=decide({'offline_since':0},{'phase':phase,'quick_eligible':True},1000)
  assert action is None


def test_wrong_or_missing_saved_account_needs_user():
 state,action=decide({'offline_since':0},{'quick_eligible':False},100)
 assert action is None and state['status']=='login_required'


def test_online_resets_retry_state_and_container_start_is_bounded():
 state,action=decide({'attempts':[1,2,3],'requires_login':True},{'online':True},100)
 assert state['attempts']==[] and not state['requires_login'] and action is None
 state,action=decide({'offline_since':0},{'account_stopped':True},100)
 assert action=='start_account'
 state,action=decide(state,{'account_stopped':True},200)
 assert action is None


def test_explicit_verification_failure_stays_paused_until_online():
 state,action=decide({'requires_login':True,'offline_since':0},{'quick_eligible':True},10000)
 assert state['status']=='login_required' and action is None
 state,action=decide(state,{'online':True},10001)
 assert not state['requires_login']


def test_stale_logged_in_but_offline_client_restarts_only_once_per_hour():
 state={'offline_since':0,'attempts':[100,200],'last_action_error':'stale_login_state'}
 state,action=decide(state,{'quick_eligible':True},400)
 assert action=='restart_account'
 state,action=decide(state,{'quick_eligible':True},600)
 assert action!='restart_account'
 state['requires_login']=True
 _,action=decide(state,{'quick_eligible':True},5000)
 assert action is None
