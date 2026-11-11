'use strict';
(() => {
  let timer,checking,expired=false;
  const controls=document.getElementById('account-controls'),status=document.getElementById('auth-status');
  const target=()=>location.pathname+location.search+location.hash;
  function expire(code){
    if(expired)return;expired=true;clearInterval(timer);
    location.replace((code==='PASSWORD_CHANGE_REQUIRED'?'/account/':'/login/')+'?next='+encodeURIComponent(target()));
  }
  async function check(){
    if(checking)return checking;
    checking=(async()=>{
      try{
        const response=await fetch('/api/auth/me',{credentials:'same-origin',cache:'no-store'});
        if(response.status===401){expire();return null;}
        if(!response.ok)return null;
        const profile=await response.json();
        if(!profile.auth_enabled){controls.hidden=true;clearInterval(timer);return profile;}
        if(profile.must_change_password){expire('PASSWORD_CHANGE_REQUIRED');return null;}
        controls.hidden=false;document.getElementById('session-user').textContent=profile.username;
        document.getElementById('change-password').href='/account/?next='+encodeURIComponent(target());
        if(!timer)timer=setInterval(()=>{if(!document.hidden)check();},10000);
        return profile;
      }catch(_){return null;}
      finally{checking=null;}
    })();
    return checking;
  }
  async function logout(){
    const button=document.getElementById('logout');button.disabled=true;
    try{const response=await fetch('/api/auth/logout',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-Catalog-Client':'web'},body:'{}'});if(!response.ok)throw new Error('暂时无法退出，请重试');expire();}
    catch(error){status.textContent=error.message;}
    finally{button.disabled=false;}
  }
  document.getElementById('logout').onclick=logout;
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)check();});
  window.addEventListener('pageshow',()=>{expired=false;check();});
  window.addEventListener('pagehide',()=>{clearInterval(timer);timer=null;});
  timer=setInterval(()=>{if(!document.hidden)check();},10000);
  window.CatalogAuth={ready:check(),check,expire,logout,get expired(){return expired;}};
})();
