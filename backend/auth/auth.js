'use strict';
(() => {
  const $=id=>document.getElementById(id);
  function destination(){
    const value=new URLSearchParams(location.search).get('next')||'/preview/';
    if(!value.startsWith('/preview/')||/[\\\x00-\x1f]/.test(value))return '/preview/';
    const parsed=new URL(value,location.origin);
    if(parsed.origin!==location.origin)return '/preview/';
    return value+(location.hash&&!value.includes('#')?location.hash:'');
  }
  const next=destination(),account=location.pathname.startsWith('/account');
  function redirect(path){location.replace(path+'?next='+encodeURIComponent(next));}
  async function post(path,body){
    const response=await fetch('/api/auth/'+path,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-Catalog-Client':'web'},body:JSON.stringify(body)});
    const data=await response.json();
    if(!response.ok)throw Object.assign(new Error(data.message||'操作失败，请稍后再试'),{status:response.status});
    return data;
  }
  $('login-form').onsubmit=async event=>{
    event.preventDefault();$('submit-login').disabled=true;$('feedback').textContent='正在登录…';
    try{const data=await post('login',{username:$('username').value.trim(),password:$('password').value});$('password').value='';if(data.must_change_password)redirect('/account/');else location.replace(next);}
    catch(error){$('feedback').textContent=error.message;}
    finally{$('submit-login').disabled=false;}
  };
  $('password-form').onsubmit=async event=>{
    event.preventDefault();
    if($('new-password').value!==$('confirm-password').value){$('feedback').textContent='两次输入的新密码不一致';return;}
    $('submit-password').disabled=true;$('feedback').textContent='正在保存…';
    try{await post('password',{current_password:$('current-password').value,new_password:$('new-password').value});$('password-form').reset();location.replace(next);}
    catch(error){if(error.status===401)redirect('/login/');else $('feedback').textContent=error.message;}
    finally{$('submit-password').disabled=false;}
  };
  $('signout').onclick=async()=>{try{await post('logout',{});redirect('/login/');}catch(error){$('feedback').textContent=error.message;}};
  (async()=>{
    try{
      const response=await fetch('/api/auth/me',{credentials:'same-origin',cache:'no-store'});
      if(response.status===401){if(account)redirect('/login/');return;}
      const profile=await response.json();if(!response.ok)throw new Error(profile.message||'暂时无法检查登录状态');
      if(!profile.auth_enabled){location.replace(next);return;}
      if(!account){if(profile.must_change_password)redirect('/account/');else location.replace(next);return;}
      $('login-form').hidden=true;$('password-form').hidden=false;$('signout').hidden=false;
      $('form-title').textContent=profile.must_change_password?'设置新的密码':'修改密码';
      $('form-description').textContent=profile.must_change_password?'首次登录，请先修改临时密码。':'保存后，继续浏览你的图鉴。';
      $('account-username').textContent=profile.username;
    }catch(error){$('feedback').textContent=error.message;}
  })();
})();
