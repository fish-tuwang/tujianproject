const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),assert=require('node:assert/strict');
const {chromium,webkit,devices}=require('playwright');
const base=process.env.PREVIEW_URL||'https://117.72.11.77',credentialsPath=process.env.CATALOG_AUTH_CREDENTIALS,statePath=process.env.CATALOG_AUTH_STATE;
const report={status:'fail',checks:[],profiles:[],errors:[]},secrets=new Set(),out='artifacts/acceptance';
const check=(label,value)=>{assert.ok(value,label);report.checks.push(label);console.log('PASS '+label);};
const clean=value=>{let text=String(value);for(const secret of secrets)if(secret)text=text.split(secret).join('[redacted]');return text;};
function privateSave(filename,value){fs.mkdirSync(path.dirname(filename),{recursive:true});fs.writeFileSync(filename,JSON.stringify(value,null,2),{mode:0o600});}
(async()=>{
 if(!credentialsPath||!statePath)throw new Error('请指定私有凭证和会话文件路径');
 const url=new URL(base);if(url.protocol!=='https:'&&!['127.0.0.1','localhost'].includes(url.hostname))throw new Error('公网认证验收必须使用受信任HTTPS');
 let credentials;try{credentials=JSON.parse(fs.readFileSync(credentialsPath,'utf8'));}catch(_){throw new Error('私有凭证文件无法读取');}
 secrets.add(credentials.password);
 const remember=async c=>{for(const cookie of await c.cookies())secrets.add(cookie.value);};
 const catalog=p=>p.waitForFunction(()=>typeof state!=='undefined'&&!state.loading&&state.items.length>0&&!restoringBrowse);
 async function signIn(p,c){await p.goto(base+'/login/',{waitUntil:'domcontentloaded'});await p.locator('#username').fill(credentials.username);await p.locator('#password').fill(credentials.password);await p.locator('#submit-login').click();await p.waitForURL(u=>u.pathname.startsWith('/preview/')||u.pathname.startsWith('/account/'));await remember(c);}
 async function change(p,c){
  if(!p.url().includes('/account/'))await p.goto(base+'/account/?next='+encodeURIComponent('/preview/?catalog=tomica'));
  await p.locator('#password-form').waitFor({state:'visible'});
  const replacement=crypto.randomBytes(24).toString('base64url');secrets.add(replacement);
  await p.locator('#current-password').fill(credentials.password);await p.locator('#new-password').fill(replacement);await p.locator('#confirm-password').fill(replacement);
  const changed=p.waitForResponse(r=>new URL(r.url()).pathname==='/api/auth/password'&&r.request().method()==='POST');await p.locator('#submit-password').click();
  await p.waitForURL(u=>u.pathname.startsWith('/preview/'));await catalog(p);await remember(c);
  credentials={username:credentials.username,password:replacement,must_change_password:false};privateSave(credentialsPath,credentials);
  return (await (await changed).allHeaders())['set-cookie']||'';
 }
 for(const profile of [{name:'desktop',engine:chromium,options:{viewport:{width:1440,height:1000}}},{name:'mobile',engine:webkit,options:{...devices['iPhone 13'],deviceScaleFactor:1}}]){
  const browser=await profile.engine.launch(profile.engine===chromium?{headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'}:{headless:true});
  try{
   const a=await browser.newContext(profile.options),p=await a.newPage();p.on('pageerror',e=>report.errors.push(clean(e.message)));
   const pass=(label,value)=>check(profile.name+' '+label,value);
   const noauth=await a.request.get(base+'/api/tomica?limit=1');pass('anonymous API is rejected',noauth.status()===401);
   const raw=await a.request.get(base+'/preview/app.js');pass('anonymous private scripts are rejected',raw.status()===401);
   await p.goto(base+'/preview/?catalog=tomica');await p.waitForURL(u=>u.pathname==='/login/');
   pass('anonymous catalog opens login without registration',await p.locator('#login-form').isVisible()&&await p.getByRole('link',{name:/注册/}).count()===0&&await p.locator('form').count()===2);
   await p.screenshot({path:out+'/private-auth-login-'+profile.name+'.png'});
   await p.locator('#username').fill(credentials.username);await p.locator('#password').fill('incorrect-password-for-test-only');await p.locator('#submit-login').click();await p.waitForFunction(()=>document.getElementById('feedback').textContent.includes('账号或密码错误'));
   pass('wrong password grants no session', (await a.request.get(base+'/api/auth/me')).status()===401);
   await signIn(p,a);const required=p.url().includes('/account/');
   if(profile.name==='desktop')pass('initial temporary password requires replacement',required);
   const setCookie=await change(p,a);pass('password change opens a usable private catalog',await p.locator('#session-user').textContent()===credentials.username);
   const cookies=await a.cookies(),cookie=cookies.find(c=>c.name==='catalog_session');
   pass('cookie is HttpOnly and uses protected transport',Boolean(cookie&&cookie.httpOnly&&/;\s*SameSite=lax(?:;|$)/i.test(setCookie)&&(url.protocol!=='https:'||cookie.secure)));
   const listResponse=await a.request.get(base+'/api/tomica?limit=1');const list=await listResponse.json();
   pass('private API is not publicly cacheable',listResponse.ok()&&listResponse.headers()['cache-control'].includes('no-store'));
   const image=list.items[0].preview_image_url||list.items[0].image_url;assert.ok(image,'real registered image is present');
   const authorized=await a.request.get(new URL(image,base).href);pass('authenticated original is available',authorized.ok()&&authorized.headers()['content-type'].startsWith('image/'));
   const anonymous=await browser.newContext(profile.options);const denied=await anonymous.request.get(new URL(image,base).href,{headers:{'If-None-Match':authorized.headers().etag||'"cached"'}});
   pass('cached original still requires current authentication',denied.status()===401);
   const asset=fs.readdirSync('backend/preview/news-assets').find(name=>name.endsWith('.jpg'));
   pass('monthly static original is private',(await anonymous.request.get(base+'/preview/news-assets/'+asset)).status()===401);await anonymous.close();
   const b=await browser.newContext(profile.options),other=await b.newPage();other.on('pageerror',e=>report.errors.push(clean(e.message)));await signIn(other,b);await catalog(other);
   pass('a new browser login revokes the old session immediately',(await a.request.get(base+'/api/pokemon?limit=1')).status()===401);
   await a.request.post(base+'/api/auth/logout',{headers:{'X-Catalog-Client':'web'},data:{}});
   pass('old logout cannot revoke the new browser',(await b.request.get(base+'/api/auth/me')).status()===200);
   await p.evaluate(()=>window.CatalogAuth?.check());await p.waitForURL(u=>u.pathname==='/login/');pass('the old page returns to login',await p.locator('#login-form').isVisible());
   pass('there is no registration endpoint',(await b.request.post(base+'/api/auth/register',{headers:{'X-Catalog-Client':'web'},data:{username:'unexpected',password:'unregistered-password-123'}})).status()===404);
   const csrf=await b.request.post(base+'/api/auth/password',{headers:{'X-Catalog-Client':'web',Origin:'https://other.invalid'},data:{current_password:credentials.password,new_password:'not-accepted-cross-site-password'}});
   pass('cross-site mutation is denied',csrf.status()===403&&(await b.request.get(base+'/api/auth/me')).status()===200);
   await other.locator('#logout').click();await other.waitForURL(u=>u.pathname==='/login/');pass('logout invalidates server access',(await b.request.get(base+'/api/tomica')).status()===401);
   report.profiles.push({name:profile.name,status:'pass'});await a.close();await b.close();
  }finally{await browser.close();}
 }
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
 try{const context=await browser.newContext(),p=await context.newPage();await signIn(p,context);await catalog(p);await context.storageState({path:statePath});fs.chmodSync(statePath,0o600);}finally{await browser.close();}
 check('no JavaScript errors',report.errors.length===0);report.status='pass';privateSave(out+'/private-auth-public.json',report);console.log(JSON.stringify({status:report.status,checks:report.checks.length,profiles:report.profiles}));
})().catch(error=>{report.errors.push(clean(String(error.message).split('\n')[0]));privateSave(out+'/private-auth-public.json',report);console.error('AUTH_ACCEPTANCE_FAILED '+clean(String(error.message).split('\n')[0]));process.exitCode=1;});
