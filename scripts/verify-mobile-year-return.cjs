const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium,webkit,devices}=require('playwright');
(async()=>{
 const local=process.argv.includes('--local'),base=process.env.PREVIEW_URL||'http://117.72.11.77',output=path.resolve('artifacts/acceptance');
 const report={status:'fail',mode:local?'local frontend with live read-only API':'public',assertions:0,checks:[],errors:[],profiles:[]};
 const check=(name,value)=>{assert.ok(value,name);report.assertions++;report.checks.push(name);console.log('PASS '+name);};
 const snapshot=p=>p.evaluate(()=>({query:{...state.query},page:state.page,pageSize:state.pageSize,ids:state.items.map(i=>i.id),scrollY}));
 const identity=value=>JSON.stringify({query:Object.fromEntries(Object.entries(value.query).sort()),page:value.page,pageSize:value.pageSize,ids:value.ids});
 const stable=(p)=>p.waitForFunction(()=>!state.loading&&state.items.length>0);
 const detail=(p)=>p.waitForFunction(()=>document.querySelector('#detail-dialog').open&&document.querySelector('.detail-content h2'));
 const afterClose=async(p)=>{await p.waitForFunction(()=>!document.querySelector('#detail-dialog').open&&!state.loading);await p.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));};
 const configure=async(p,year)=>{await p.locator('#year').selectOption(year);await p.waitForFunction(y=>!state.loading&&state.query.year===y,year);};
 const overlay=async(p)=>{if(local)await p.route('**/preview/**',async route=>{const file=new URL(route.request().url()).pathname.split('/').pop()||'index.html';if(['index.html','app.js','style.css','pokemon-details.js'].includes(file))await route.fulfill({path:path.resolve('backend/preview',file),contentType:file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html'});else await route.continue();});};
 for(const profile of [{name:'chrome-touch',engine:chromium,options:{...devices['iPhone 14 Pro Max']}},{name:'webkit-touch',engine:webkit,options:{...devices['iPhone 14 Pro Max']}},{name:'chrome-desktop',engine:chromium,options:{viewport:{width:1440,height:1050}}}]){
  const browser=await profile.engine.launch(profile.engine===chromium?{headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'}:{headless:true});
  try{
   const context=await browser.newContext(profile.options),p=await context.newPage();await overlay(p);p.on('pageerror',e=>report.errors.push(profile.name+': '+e.message));
   const click=locator=>profile.options.hasTouch?locator.tap():locator.click();
   await p.goto(base+'/preview/?catalog=tomica&v=0.6.1',{waitUntil:'domcontentloaded'});await stable(p);
   await configure(p,'2026');await p.locator('.catalog-card').nth(5).scrollIntoViewIfNeeded();
   let before=await snapshot(p);await p.locator('.catalog-card').nth(5).scrollIntoViewIfNeeded();before=await snapshot(p);await click(p.locator('.catalog-card').nth(5));await detail(p);
   await p.locator('#detail-dialog').evaluate(e=>e.scrollTop=e.scrollHeight);
   await click(p.locator('#close-detail'));await afterClose(p);
   let after=await snapshot(p);
   check(profile.name+' 2026 sixth car closes to exactly the filtered list',identity(before)===identity(after)&&await p.locator('#year').inputValue()==='2026');
   check(profile.name+' normal close restores original list position',Math.abs(before.scrollY-after.scrollY)<=3&&after.scrollY>300);
   await p.locator('.catalog-card').nth(5).scrollIntoViewIfNeeded();before=await snapshot(p);await click(p.locator('.catalog-card').nth(5));await detail(p);await p.evaluate(()=>window.scrollTo({top:0,behavior:'instant'}));await click(p.locator('#close-detail'));await afterClose(p);after=await snapshot(p);
   if(Math.abs(after.scrollY-before.scrollY)>3||identity(after)!==identity(before))console.log('SCROLL_DIAGNOSTIC '+JSON.stringify({before,after,saved:await p.evaluate(()=>sessionStorage.getItem(tomicaListKey))}));
   check(profile.name+' closing repairs browser focus/background scroll jumps',Math.abs(after.scrollY-before.scrollY)<=3&&identity(after)===identity(before));
   await p.locator('.catalog-card').nth(5).scrollIntoViewIfNeeded();before=await snapshot(p);await click(p.locator('.catalog-card').nth(5));await detail(p);await p.reload({waitUntil:'domcontentloaded'});await detail(p);await click(p.locator('#close-detail'));await afterClose(p);after=await snapshot(p);
   check(profile.name+' reloading detail does not lose the selected year or cars',identity(after)===identity(before)&&await p.locator('#year').inputValue()==='2026');
   check(profile.name+' reloading detail retains its return position',Math.abs(after.scrollY-before.scrollY)<=3);
   await p.reload({waitUntil:'domcontentloaded'});await stable(p);await p.waitForFunction(()=>document.getElementById('year').value==='2026');
   check(profile.name+' list reload keeps the same selected year',await p.evaluate(()=>state.query.year==='2026'&&state.items.every(i=>i.release_year===2026)));
   await configure(p,'2025');await p.locator('#next-page').click();await p.waitForFunction(()=>!state.loading&&state.page===2);await p.locator('.catalog-card').nth(2).scrollIntoViewIfNeeded();before=await snapshot(p);
   await click(p.locator('.catalog-card').nth(2));await detail(p);await p.reload({waitUntil:'domcontentloaded'});await detail(p);await click(p.locator('#close-detail'));await afterClose(p);after=await snapshot(p);
   check(profile.name+' 2025 page two survives detail reload and close',identity(after)===identity(before)&&after.page===2&&await p.locator('#year').inputValue()==='2025');
   await p.locator('#page-size').selectOption('40');await p.waitForFunction(()=>!state.loading&&state.pageSize===40);await p.locator('#search').fill('Toyota');await p.waitForFunction(()=>!state.loading&&state.query.q==='Toyota'&&state.items.length>0);before=await snapshot(p);
   await p.locator('.catalog-card').first().scrollIntoViewIfNeeded();before=await snapshot(p);await click(p.locator('.catalog-card').first());await detail(p);await p.reload({waitUntil:'domcontentloaded'});await detail(p);await click(p.locator('#close-detail'));await afterClose(p);after=await snapshot(p);
   check(profile.name+' year plus name search and forty-card size survive reload',identity(after)===identity(before)&&after.pageSize===40&&await p.locator('#search').inputValue()==='Toyota');
   await click(p.locator('#reset'));await p.waitForFunction(()=>!state.loading&&Object.keys(state.query).length===0);await p.reload({waitUntil:'domcontentloaded'});await stable(p);
   check(profile.name+' explicit reset remains cleared after reload',await p.evaluate(()=>!state.query.year&&!state.query.q&&document.getElementById('year').value===''));
   await configure(p,'2026');await p.locator('.catalog-card').nth(5).scrollIntoViewIfNeeded();before=await snapshot(p);await p.locator('.catalog-card').nth(5).scrollIntoViewIfNeeded();before=await snapshot(p);await click(p.locator('.catalog-card').nth(5));await detail(p);await p.goBack();await afterClose(p);
   check(profile.name+' browser back restores filtered list and position',identity(await snapshot(p))===identity(before)&&Math.abs((await snapshot(p)).scrollY-before.scrollY)<=3);
   await p.locator('.catalog-card').nth(5).scrollIntoViewIfNeeded();before=await snapshot(p);await click(p.locator('.catalog-card').nth(5));await detail(p);await p.keyboard.press('Escape');await afterClose(p);
   check(profile.name+' Escape closes without clearing the selected year',await p.evaluate(()=>state.query.year==='2026')&&Math.abs((await snapshot(p)).scrollY-before.scrollY)<=3);
   if(profile.name==='chrome-touch'){
    await p.locator('#page-size').selectOption('20');await p.waitForFunction(()=>!state.loading&&state.pageSize===20);
    const carId=await p.evaluate(()=>state.items[5].id);let release,started;
    const gate=new Promise(r=>release=r),seen=new Promise(r=>started=r);
    await p.route('**/api/tomica?**',async route=>{const u=new URL(route.request().url());if(u.searchParams.get('limit')==='40'&&u.searchParams.get('year')==='2026'){started();await gate;}await route.continue();});
    await p.locator('#page-size').selectOption('40');await seen;
    await p.evaluate(id=>location.hash='tomica/'+id,carId);await detail(p);
    const loaded=p.waitForResponse(r=>{const u=new URL(r.url());return u.pathname==='/api/tomica'&&u.searchParams.get('limit')==='40'&&u.searchParams.get('year')==='2026';});release();await loaded;await stable(p);
    await click(p.locator('#close-detail'));await afterClose(p);
    check('temporary empty list while filtering cannot reset the selected year',await p.evaluate(()=>state.query.year==='2026'&&state.pageSize===40&&state.items.every(i=>i.release_year===2026)));
   }
   await p.screenshot({path:output+'/year-return-'+profile.name+'-'+(local?'local':'public')+'.png'});
   report.profiles.push({name:profile.name,status:'pass'});
   await context.close();
  }finally{await browser.close();fs.writeFileSync(output+'/mobile-year-return-'+(local?'local':'public')+'.json',JSON.stringify(report,null,2));}
 }
 check('no JavaScript runtime errors',report.errors.length===0);report.status='pass';fs.writeFileSync(output+'/mobile-year-return-'+(local?'local':'public')+'.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report));
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
