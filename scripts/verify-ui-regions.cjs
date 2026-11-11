const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium,webkit,devices}=require('playwright');
const base=process.env.PREVIEW_URL||'http://117.72.11.77',local=process.argv.includes('--local'),out='artifacts/acceptance';
const report={status:'fail',checks:[],errors:[],profiles:[]};
const check=(name,value)=>{assert.ok(value,name);report.checks.push(name);console.log('PASS '+name);};
const ready=(p,count)=>p.waitForFunction(count=>!state.loading&&!restoringBrowse&&state.items.length===count,count);
const snapshot=p=>p.evaluate(()=>({ids:state.items.map(i=>i.dex||i.id),query:{...state.query},y:scrollY}));
const same=(a,b)=>JSON.stringify(a.ids)===JSON.stringify(b.ids)&&JSON.stringify(Object.entries(a.query).sort())===JSON.stringify(Object.entries(b.query).sort());
async function scrollNext(p,count){await p.evaluate(()=>window.scrollBy(0,-220));await p.locator('#scroll-sentinel').scrollIntoViewIfNeeded();await p.evaluate(()=>window.scrollBy(0,220));await ready(p,count);}
async function overlay(p){if(local)await p.route('**/preview/**',async r=>{const relative=new URL(r.request().url()).pathname.slice('/preview/'.length)||'index.html';if(['index.html','app.js','style.css','theme.css','pokemon-details.js','backgrounds/tomica-track.svg','backgrounds/pokemon-map.svg'].includes(relative))await r.fulfill({path:path.resolve('backend/preview',relative),contentType:relative.endsWith('.svg')?'image/svg+xml':relative.endsWith('.css')?'text/css':relative.endsWith('.js')?'text/javascript':'text/html'});else await r.continue();});}
(async()=>{
 for(const profile of [{name:'desktop',engine:chromium,options:{viewport:{width:1440,height:1100}}},{name:'mobile',engine:webkit,options:{...devices['iPhone 13'],deviceScaleFactor:1}}]){
  const b=await profile.engine.launch(profile.engine===chromium?{headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'}:{headless:true});
  try{
   const c=await b.newContext(profile.options),p=await c.newPage();await overlay(p);p.on('pageerror',e=>report.errors.push(profile.name+': '+e.message));let requests=0;p.on('request',r=>{if(new URL(r.url()).pathname==='/api/pokemon')requests++;});
   const pass=(n,v)=>check(profile.name+' '+n,v);
   await p.goto(base+'/preview/?catalog=pokemon&v=0.9.0',{waitUntil:'domcontentloaded'});await ready(p,12);
   pass('there is no continue-exploring button',await p.locator('#load-more').count()===0);
   pass('ten regions plus national index are available',await p.locator('.region-tab').count()===11&&await p.locator('#region option').count()===11);
   pass('Pokemon does not display car filters',!await p.locator('#brand-wrap').isVisible()&&!await p.locator('#year-wrap').isVisible());
   pass('brand icon drawing is preserved',await p.locator('.brand-icon path').getAttribute('d')==='M16 3 29 16 16 29 3 16Z M16 10 22 16 16 22 10 16Z');
   await p.waitForFunction(()=>document.querySelector('.feature-illustration img')?.naturalWidth>0);await p.screenshot({path:out+'/ui-regions-pokemon-'+profile.name+'.png'});
   await p.locator('#region').selectOption('hisui');await ready(p,12);
   pass('region dropdown and quick tab agree',await p.locator('[data-region="hisui"]').getAttribute('aria-pressed')==='true'&&await p.evaluate(()=>state.query.region==='hisui'&&state.total===242));
   await p.evaluate(()=>window.scrollTo({top:0,behavior:'instant'}));await p.waitForFunction(()=>[...document.querySelectorAll('.catalog-card img')].slice(0,4).every(i=>i.naturalWidth>0));await p.screenshot({path:out+'/ui-regions-pokemon-'+profile.name+'.png'});
   for(const count of [24,36,48])await scrollNext(p,count);
   const batch=await snapshot(p),idleRequests=requests;await p.waitForTimeout(400);
   pass('scroll loads three batches in national order without duplicates',batch.ids.length===48&&new Set(batch.ids).size===48&&batch.ids.every((v,i)=>!i||v>batch.ids[i-1]));
   pass('standing still does not drain the entire region',requests===idleRequests&&await p.evaluate(()=>!state.loading&&state.items.length===48));
   await p.locator('.catalog-card').nth(18).scrollIntoViewIfNeeded();const before=await snapshot(p);
   await (profile.options.hasTouch?p.locator('.catalog-card').nth(18).tap():p.locator('.catalog-card').nth(18).click());await p.locator('.detail-content h2').waitFor();
   const paused=requests;await p.evaluate(()=>window.scrollTo(0,document.body.scrollHeight));await p.waitForTimeout(350);
   pass('detail dialog pauses automatic browsing',requests===paused&&await p.evaluate(()=>state.items.length===48));
   await p.locator('#close-detail').click();await p.waitForFunction(y=>Math.abs(scrollY-y)<=3,before.y);
   pass('detail return preserves region, records and position',same(await snapshot(p),before));
   await p.reload({waitUntil:'domcontentloaded'});await ready(p,48);await p.waitForFunction(y=>Math.abs(scrollY-y)<=3,before.y);
   pass('refresh restores the same region and loaded progress',same(await snapshot(p),before)&&await p.locator('#region').inputValue()==='hisui');
   await scrollNext(p,60);pass('scrolling after restoration resumes the next cursor',new Set((await snapshot(p)).ids).size===60);

   await p.locator('[data-region="kanto"]').click();await ready(p,12);await p.locator('#type').selectOption('草');await ready(p,12);
   const total=await p.evaluate(()=>state.total);await scrollNext(p,total);
   const ended=requests;await p.evaluate(()=>window.scrollTo(0,document.body.scrollHeight));await p.waitForTimeout(350);
   pass('short final batch finishes and stops requesting',total>12&&total<24&&requests===ended&&await p.locator('#scroll-sentinel').isHidden()&&await p.evaluate(()=>state.cursor===null));

   await p.locator('#reset').click();await ready(p,12);const original=await snapshot(p);let failed=0;
   const fail=async r=>{if(new URL(r.request().url()).searchParams.has('cursor')&&failed++===0)await r.fulfill({status:503,contentType:'application/json',body:JSON.stringify({message:'测试网络中断'})});else await r.continue();};
   await p.route('**/api/pokemon?**',fail);await p.evaluate(()=>window.scrollBy(0,-200));await p.locator('#scroll-sentinel').scrollIntoViewIfNeeded();
   await p.locator('#feedback button').waitFor();const failedIds=await snapshot(p);await p.waitForTimeout(350);
   pass('failed automatic append keeps all existing records and stops retrying',JSON.stringify(original.ids)===JSON.stringify(failedIds.ids)&&failed===1);
   await p.locator('#feedback button').click();await ready(p,24);await p.unroute('**/api/pokemon?**',fail);
   pass('retry continues the original cursor without duplicates',new Set((await snapshot(p)).ids).size===24&&JSON.stringify((await snapshot(p)).ids.slice(0,12))===JSON.stringify(original.ids));

   if(profile.name==='desktop'){
    let release,seen,finished;const gate=new Promise(r=>release=r),started=new Promise(r=>seen=r),done=new Promise(r=>finished=r);
    const hold=async r=>{if(new URL(r.request().url()).searchParams.has('cursor')){seen();await gate;try{await r.continue();}catch(e){if(!/abort|cancel/i.test(r.request().failure()?.errorText||e.message))throw e;}finally{finished();}}else await r.continue();};
    await p.route('**/api/pokemon?**',hold);
    await p.evaluate(()=>window.scrollBy(0,-220));await p.locator('#scroll-sentinel').scrollIntoViewIfNeeded();await started;
    await p.locator('#region').selectOption('kanto');await ready(p,12);release();await done;await p.waitForTimeout(250);await p.unroute('**/api/pokemon?**',hold);
    pass('a late old cursor cannot overwrite a newly selected region',await p.evaluate(()=>state.query.region==='kanto'&&state.items.length===12));
    const tall=await c.newPage();await overlay(tall);await tall.setViewportSize({width:1440,height:2800});await tall.goto(base+'/preview/?catalog=pokemon&v=0.9.0');
    await tall.waitForFunction(()=>!state.loading&&!restoringBrowse&&document.documentElement.scrollHeight>innerHeight+30);
    const filled=await tall.evaluate(()=>state.items.length);await tall.waitForTimeout(350);
    pass('a tall viewport fills itself and stops once scrollable',filled>12&&filled<72&&await tall.evaluate(n=>state.items.length===n,filled));await tall.close();
   }

   await p.locator('#region').selectOption('paldea');await ready(p,12);await p.locator('#type').selectOption('钢');await ready(p,12);await p.locator('#search').fill('赛富豪');await ready(p,1);
   pass('region, attribute and name filter intersect',await p.evaluate(()=>state.items[0].dex===1000&&state.total===1&&state.query.region==='paldea'&&state.query.type==='钢'));
   pass('mobile and desktop layouts have no horizontal overflow',await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
   const pokemon=await snapshot(p);await p.locator('[data-kind="tomica"]').click();await p.waitForFunction(()=>!state.loading&&!restoringBrowse&&state.kind==='tomica'&&state.items.length===20);
   pass('Tomica hides region and attribute controls',!await p.locator('#region-panel').isVisible()&&!await p.locator('#region-wrap').isVisible()&&!await p.locator('#type-wrap').isVisible());
   pass('Tomica keeps rounded cards and its own themed background',await p.locator('.catalog-card').first().evaluate(e=>parseFloat(getComputedStyle(e).borderRadius)>=15)&&await p.evaluate(()=>getComputedStyle(document.querySelector('.workspace'),'::before').backgroundImage.includes('tomica-track.svg')));
   await p.waitForFunction(()=>document.querySelector('.feature-illustration img')?.naturalWidth>0);await p.screenshot({path:out+'/ui-regions-tomica-'+profile.name+'.png'});
   await p.locator('[data-kind="pokemon"]').click();await ready(p,1);await p.waitForFunction(y=>Math.abs(scrollY-y)<=3,pokemon.y);
   pass('navigation between the two catalogs preserves region, attribute and search',same(await snapshot(p),pokemon));
   report.profiles.push({name:profile.name,status:'pass'});await c.close();
  }finally{await b.close();fs.writeFileSync(out+'/ui-regions-'+(local?'local':'public')+'.json',JSON.stringify(report,null,2));}
 }
 check('no JavaScript errors',report.errors.length===0);report.status='pass';console.log(JSON.stringify({status:report.status,checks:report.checks.length,profiles:report.profiles}));
 fs.writeFileSync(out+'/ui-regions-'+(local?'local':'public')+'.json',JSON.stringify(report,null,2));
})().catch(e=>{console.error(e.stack);process.exitCode=1;});
