const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium,webkit,devices}=require('playwright');
(async()=>{
 const local=process.argv.includes('--local'),base=process.env.PREVIEW_URL||'http://117.72.11.77',output=path.resolve('artifacts/acceptance');
 const report={status:'fail',mode:local?'local frontend with live read-only API':'public',assertions:0,checks:[],errors:[],profiles:[]};
 const check=(name,ok)=>{assert.ok(ok,name);report.assertions++;report.checks.push(name);console.log('PASS '+name);};
 const snap=async p=>{await settle(p);return p.evaluate(()=>({kind:state.kind,query:{...state.query},page:state.page,pageSize:state.kind==='tomica'?state.pageSize:null,ids:state.items.map(i=>i.dex||i.id),scrollY}));};
 const shape=s=>JSON.stringify({...s,query:Object.fromEntries(Object.entries(s.query).sort()),scrollY:undefined});
 const ready=async(p,kind,count,allowRestoring=false)=>{try{await p.waitForFunction(({kind,count,allowRestoring})=>state.kind===kind&&!state.loading&&(!restoringBrowse||allowRestoring)&&state.items.length===(count||state.items.length)&&state.items.length>0,{kind,count,allowRestoring});}catch(e){console.error(JSON.stringify(await p.evaluate(expected=>({expected,url:location.href,kind:state.kind,query:state.query,count:state.items.length,loading:state.loading,restoring:restoringBrowse,feedback:document.getElementById('feedback').textContent,saved:readCatalogList(state.kind)}),{kind,count})));throw e;}};
 const scrollNextBatch=async(p,count)=>{await p.waitForFunction(()=>!restoringBrowse);await p.evaluate(()=>window.scrollBy(0,-200));await p.locator('#scroll-sentinel').scrollIntoViewIfNeeded();await p.evaluate(()=>window.scrollBy(0,200));await ready(p,'pokemon',count);};
 const position=async(p,top)=>{try{await p.waitForFunction(top=>Math.abs(scrollY-top)<=3,top,{timeout:10000});}catch(e){console.error(JSON.stringify(await p.evaluate(top=>({expected:top,actual:scrollY,saved:readCatalogList(state.kind),height:document.documentElement.scrollHeight,viewport:innerHeight,restoring:restoringBrowse,news:document.getElementById('news-sidebar').getBoundingClientRect().height}),top)));throw e;}};
 const settle=p=>p.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));
 const overlay=async p=>{if(local)await p.route('**/preview/**',async route=>{const name=new URL(route.request().url()).pathname.split('/').pop()||'index.html';if(['app.js','style.css','theme.css','index.html','pokemon-details.js'].includes(name))await route.fulfill({path:path.resolve('backend/preview',name),contentType:name.endsWith('.js')?'text/javascript':name.endsWith('.css')?'text/css':'text/html'});else await route.continue();});};
 for(const profile of [{name:'desktop',engine:chromium,options:{viewport:{width:1440,height:1000}}},{name:'webkit-mobile',engine:webkit,options:devices['iPhone 14 Pro Max']}].filter(p=>!process.argv.includes('--mobile')||p.name==='webkit-mobile')){
  const b=await profile.engine.launch(profile.engine===chromium?{headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'}:{headless:true});
  try{
   const context=await b.newContext(profile.options),p=await context.newPage();await overlay(p);p.on('pageerror',e=>report.errors.push(profile.name+': '+e.message));
   const tap=locator=>profile.options.hasTouch?locator.tap():locator.click();
   await p.goto(base+'/preview/?catalog=tomica&v=0.6.3',{waitUntil:'domcontentloaded'});await ready(p,'tomica');
   await p.locator('#year').selectOption('2025');await p.waitForFunction(()=>!state.loading&&state.query.year==='2025');await p.locator('.catalog-card').nth(15).scrollIntoViewIfNeeded();let before=await snap(p);
   await p.reload({waitUntil:'domcontentloaded'});await ready(p,'tomica',before.ids.length);await position(p,before.scrollY);
   check(profile.name+' standalone car refresh preserves year and exact scroll',shape(await snap(p))===shape(before)&&await p.locator('#year').inputValue()==='2025');
   await p.locator('#next-page').click();await p.waitForFunction(()=>!state.loading&&state.page===2);await p.locator('.catalog-card').nth(2).scrollIntoViewIfNeeded();before=await snap(p);
   await p.reload({waitUntil:'domcontentloaded'});await ready(p,'tomica',before.ids.length);await position(p,before.scrollY);
   check(profile.name+' standalone car refresh preserves second page',shape(await snap(p))===shape(before));
   await p.locator('#page-size').selectOption('40');await p.waitForFunction(()=>!state.loading&&state.pageSize===40);await p.locator('.catalog-card').nth(20).scrollIntoViewIfNeeded();const car=await snap(p);
   await p.reload({waitUntil:'domcontentloaded'});await ready(p,'tomica',car.ids.length);await position(p,car.scrollY);
   check(profile.name+' standalone car refresh preserves forty-card size',shape(await snap(p))===shape(car));
   let releaseNews,newsSeen;
   const newsGate=new Promise(r=>releaseNews=r),newsStarted=new Promise(r=>newsSeen=r);
   const holdNews=async route=>{newsSeen();await newsGate;await route.continue();};
   await p.route('**/api/tomica-news',holdNews);
   try{
    await p.reload({waitUntil:'domcontentloaded'});await newsStarted;await ready(p,'tomica',car.ids.length,true);await p.waitForFunction(()=>document.getElementById('year').value==='2025');await settle(p);
    releaseNews();await p.locator('.news-feature').waitFor();await settle(p);await position(p,car.scrollY);
    check(profile.name+' late month sidebar cannot shift the restored car list',shape(await snap(p))===shape(car));
   }finally{releaseNews();await p.unroute('**/api/tomica-news',holdNews);}
   await p.goto(base+'/preview/?catalog=pokemon&v=0.6.3',{waitUntil:'domcontentloaded'});await ready(p,'pokemon',12);
   check(profile.name+' Pokemon starts without car-year or brand filters',await p.evaluate(()=>!state.query.year&&!state.query.brand&&document.getElementById('type').value===''));
   await p.locator('#type').selectOption('水');await p.waitForFunction(()=>!state.loading&&state.query.type==='水');
   for(const count of [24,36]){await scrollNextBatch(p,count);}
   await p.locator('.catalog-card').nth(20).scrollIntoViewIfNeeded();before=await snap(p);
   await p.reload({waitUntil:'domcontentloaded'});await ready(p,'pokemon',36);await position(p,before.scrollY);
   check(profile.name+' Pokemon list refresh preserves water filter, 36 rows and scroll',shape(await snap(p))===shape(before)&&await p.locator('#type').inputValue()==='水');
   await p.locator('.catalog-card').nth(20).scrollIntoViewIfNeeded();before=await snap(p);await tap(p.locator('.catalog-card').nth(20));await p.locator('.detail-content h2').waitFor();await p.locator('#detail-dialog').evaluate(e=>e.scrollTop=e.scrollHeight);
   await tap(p.locator('#close-detail'));await settle(p);await position(p,before.scrollY);
   check(profile.name+' Pokemon detail close preserves the same water list and position',shape(await snap(p))===shape(before));
   await p.locator('.catalog-card').nth(20).scrollIntoViewIfNeeded();before=await snap(p);await tap(p.locator('.catalog-card').nth(20));await p.locator('.detail-content h2').waitFor();const title=await p.locator('.detail-content h2').textContent();await p.reload({waitUntil:'domcontentloaded'});await p.locator('.detail-content h2').filter({hasText:title}).waitFor();await tap(p.locator('#close-detail'));await settle(p);await position(p,before.scrollY);
   check(profile.name+' Pokemon detail reload and close retain filter and loaded progress',shape(await snap(p))===shape(before));
   const previousIds=before.ids;await scrollNextBatch(p,48);const continued=await snap(p);
   check(profile.name+' continue loading after restore has no duplicate or skipped prior rows',new Set(continued.ids).size===48&&JSON.stringify(continued.ids.slice(0,36))===JSON.stringify(previousIds)&&continued.ids.every((id,i)=>!i||id>continued.ids[i-1]));
   await p.locator('#search').fill('伊布');await p.waitForFunction(()=>!state.loading&&state.query.q==='伊布'&&state.items.length>0);await p.locator('.catalog-card').first().scrollIntoViewIfNeeded();const pokemon=await snap(p);
   await p.reload({waitUntil:'domcontentloaded'});await ready(p,'pokemon',pokemon.ids.length);await position(p,pokemon.scrollY);
   check(profile.name+' Pokemon attribute plus name search survive standalone refresh',shape(await snap(p))===shape(pokemon)&&await p.locator('#search').inputValue()==='伊布'&&await p.locator('#type').inputValue()==='水');
   await p.goto(base+'/preview/?catalog=tomica&v=0.6.3',{waitUntil:'domcontentloaded'});await ready(p,'tomica',car.ids.length);await position(p,car.scrollY);
   check(profile.name+' car context remains independent after visiting Pokemon',shape(await snap(p))===shape(car)&&await p.locator('#year').inputValue()==='2025');
   await p.goto(base+'/preview/?catalog=pokemon&v=0.6.3',{waitUntil:'domcontentloaded'});await ready(p,'pokemon',pokemon.ids.length);await position(p,pokemon.scrollY);
   check(profile.name+' Pokemon context remains independent after visiting cars',shape(await snap(p))===shape(pokemon)&&!await p.locator('#brand-wrap').isVisible());
   await p.locator('#reset').click();await ready(p,'pokemon',12);await p.reload({waitUntil:'domcontentloaded'});await ready(p,'pokemon',12);
   check(profile.name+' explicit Pokemon reset remains cleared after refresh',await p.evaluate(()=>!Object.keys(state.query).length&&document.getElementById('search').value===''&&document.getElementById('type').value===''));
   if(profile.name==='desktop'){
    for(let n=0;n<8;n++){const count=(n+2)*12;await scrollNextBatch(p,count);}
    await p.locator('.catalog-card').nth(95).scrollIntoViewIfNeeded();before=await snap(p);await p.reload({waitUntil:'domcontentloaded'});await ready(p,'pokemon',108);await position(p,before.scrollY);
    check('desktop Pokemon progress above 100 restores every row and position',shape(await snap(p))===shape(before));
    let release,started,finished;const gate=new Promise(r=>release=r),seen=new Promise(r=>started=r),done=new Promise(r=>finished=r);
    await p.route('**/api/pokemon?**',async route=>{if(new URL(route.request().url()).searchParams.has('cursor')){started();await gate;try{await route.continue();}catch(error){if(!/abort|cancel/i.test(route.request().failure()?.errorText||''))throw error;}finally{finished();}}else await route.continue();});
    await p.reload({waitUntil:'domcontentloaded'});await seen;await p.locator('#reset').click();await ready(p,'pokemon',12);const reset=await snap(p);release();await done;await p.waitForTimeout(300);
    check('cancelled old Pokemon restoration cannot undo a new reset or scroll',shape(await snap(p))===shape(reset)&&Math.abs((await snap(p)).scrollY-reset.scrollY)<=3&&!Object.keys(reset.query).length);
   }
   await p.screenshot({path:output+'/both-catalog-refresh-'+profile.name+'-'+(local?'local':'public')+'.png'});report.profiles.push({name:profile.name,status:'pass'});await context.close();
  }finally{await b.close();fs.writeFileSync(output+'/both-catalog-refresh-'+(local?'local':'public')+'.json',JSON.stringify(report,null,2));}
 }
 check('no JavaScript errors',report.errors.length===0);report.status='pass';fs.writeFileSync(output+'/both-catalog-refresh-'+(local?'local':'public')+'.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report));
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
