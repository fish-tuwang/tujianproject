const fs=require('node:fs'),assert=require('node:assert/strict');
const {chromium,webkit,devices}=require('playwright');
const auth=require('./browser-auth.cjs');
const base=process.env.PREVIEW_URL||'https://117.72.11.77',out='artifacts/acceptance',local=new URL(base).hostname==='127.0.0.1';
const report={status:'fail',scope:local?'local server with actual partial official dataset':'deployed private HTTPS',checks:[],errors:[],profiles:[],rateLimited:[]};
const check=(name,value)=>{assert.ok(value,name);report.checks.push(name);console.log('PASS '+name);};
const ready=p=>p.waitForFunction(()=>window.GunplaPage?.state.ready&&!GunplaPage.state.loading&&GunplaPage.state.items.length>0);
const settled=p=>p.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));
const snapshot=p=>p.evaluate(()=>({query:{...GunplaPage.state.query},ids:GunplaPage.state.items.map(r=>r.id),y:scrollY}));
const shape=v=>JSON.stringify({query:v.query,ids:v.ids});
(async()=>{
 fs.mkdirSync(out,{recursive:true});
 for(const profile of [{name:'desktop',engine:chromium,options:{viewport:{width:1700,height:1050}}},{name:'mobile',engine:webkit,options:{...devices['iPhone 13'],deviceScaleFactor:1}}]){
  const browser=await profile.engine.launch(profile.engine===chromium?{headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'}:{headless:true});
  try{
   const c=await browser.newContext({...profile.options,...auth.contextOptions()}),p=await c.newPage();p.setDefaultTimeout(45000);p.on('pageerror',e=>report.errors.push(e.message));const pass=(name,value)=>check(profile.name+' '+name,value);
   p.on('response',r=>{if(r.status()===429&&new URL(r.url()).origin===base)report.rateLimited.push(new URL(r.url()).pathname);});
   if(!local&&profile.name==='desktop'){
    const anonymous=await browser.newContext();
    const document=await anonymous.request.get(base+'/preview/gunpla.html',{maxRedirects:0});
    pass('anonymous Gunpla document redirects to login',document.status()===303&&document.headers().location.startsWith('/login/'));
    pass('anonymous Gunpla API is denied',(await anonymous.request.get(base+'/api/gunpla')).status()===401);
    pass('anonymous Gunpla JavaScript is denied',(await anonymous.request.get(base+'/preview/gunpla.js')).status()===401);
    await anonymous.close();
   }
   await p.goto(base+'/preview/gunpla.html',{waitUntil:'domcontentloaded'});await ready(p);
   pass('all seventeen model grades are visible without accessory-only categories',await p.locator('[data-grade]').count()===18&&!/高达水贴|BUILDERS PARTS|可动底座|高达模型 配件套组/.test(await p.locator('#grade-options').textContent()));
   pass('all four sale categories stay in a fixed in-page selector',await p.locator('[data-sale]').count()===4);
   pass('initial page has twenty model covers and no gallery arrays',await p.locator('.gunpla-card').count()===20&&await p.evaluate(()=>GunplaPage.state.items.every(r=>!('gallery' in r)&&!('gallery_urls' in r))));
   pass('old car and Pokemon search controls are absent',await p.locator('#brand-wrap,#year-wrap,#region-panel,#type-wrap').count()===0);
   pass('activity and release previews are present',await p.locator('.event-card').count()>0&&await p.locator('.release-item').count()>0);
   // Mobile lazy images start below the tall grade selector; expose each tested cover.
   for(let index=0;index<5;index++)await p.locator('.gunpla-card-image img').nth(index).scrollIntoViewIfNeeded();
   await p.waitForFunction(()=>[...document.querySelectorAll('.gunpla-card-image img')].slice(0,5).every(i=>i.complete&&i.naturalWidth>0),{},{timeout:120000});
   if(!local&&profile.name==='desktop'){
    const anonymous=await browser.newContext(),url=await p.locator('.gunpla-card-image img').first().evaluate(i=>i.src);
    pass('a cached Gunpla cover still requires authentication',(await anonymous.request.get(url,{headers:{'If-None-Match':'"cached"'}})).status()===401);
    pass('standalone LED and frame accessories are absent',(await c.request.get(base+'/api/gunpla/products/2150')).status()===404&&(await c.request.get(base+'/api/gunpla/products/2035')).status()===404);
    await anonymous.close();
   }
   pass('covers fill their entire rounded image frame',await p.locator('.gunpla-card-image img').first().evaluate(i=>{const a=i.getBoundingClientRect(),b=i.parentElement.getBoundingClientRect();return getComputedStyle(i).objectFit==='cover'&&Math.abs(a.width-b.width)<2&&Math.abs(a.height-b.height)<2;}));
   if(profile.name==='desktop')pass('desktop keeps five model columns',await p.locator('#gunpla-cards').evaluate(e=>getComputedStyle(e).gridTemplateColumns.split(' ').length===5));
   const pathname=new URL(p.url()).pathname;
   await p.locator('[data-grade="15"]').click();await p.waitForFunction(()=>!GunplaPage.state.loading&&GunplaPage.state.query.grade==='15');
   await p.locator('[data-sale="3"]').click();await p.waitForFunction(()=>!GunplaPage.state.loading&&GunplaPage.state.query.sale_type==='3');
   pass('grade and limited category intersect without page navigation',new URL(p.url()).pathname===pathname&&await p.evaluate(()=>GunplaPage.state.items.length>0&&GunplaPage.state.items.every(r=>r.brand_ids.includes('15')&&r.sale_types.includes('3'))));
   await p.locator('[data-mode="series"]').click();await p.locator('#open-series').click();
   pass('work picker groups works by real release decades',await p.locator('.series-decade[data-decade="1970"]').count()===1&&await p.locator('.series-decade[data-decade="1990"]').count()===1&&await p.locator('.series-decade[data-decade="2020"]').count()===1&&await p.locator('[data-series]').count()===39);
   await p.locator('[data-series="28"]').click();await p.waitForFunction(()=>!GunplaPage.state.loading&&GunplaPage.state.query.series==='28');
   pass('work mode clears grade and sale restriction and keeps one work',await p.evaluate(()=>!GunplaPage.state.query.grade&&!GunplaPage.state.query.sale_type&&GunplaPage.state.items.length>0&&GunplaPage.state.items.every(r=>r.series_ids.includes('28')))&&!await p.locator('#sale-types').isVisible());
   await p.locator('#gunpla-search').fill('飞翼');await p.waitForFunction(()=>!GunplaPage.state.loading&&GunplaPage.state.query.q==='飞翼');
   pass('name search intersects selected work',await p.evaluate(()=>GunplaPage.state.items.length>0&&GunplaPage.state.items.every(r=>r.name.includes('飞翼')&&r.series_ids.includes('28'))));
   await p.reload({waitUntil:'domcontentloaded'});await ready(p);pass('refresh preserves work name and search',await p.evaluate(()=>GunplaPage.state.query.mode==='series'&&GunplaPage.state.query.series==='28'&&GunplaPage.state.query.q==='飞翼'));
   await p.locator('#gunpla-reset').click();await p.waitForFunction(()=>!GunplaPage.state.loading&&GunplaPage.state.query.q==='');
   await p.locator('#gunpla-page-size').selectOption('40');await p.waitForFunction(()=>!GunplaPage.state.loading&&GunplaPage.state.query.limit===40&&GunplaPage.state.items.length===40);
   await p.locator('#gunpla-next').click();await p.waitForFunction(()=>!GunplaPage.state.loading&&GunplaPage.state.query.page===2);await p.locator('.gunpla-card').nth(20).scrollIntoViewIfNeeded();await settled(p);const before=await snapshot(p);
   await p.evaluate(()=>GunplaPage.openProduct('3425'));await p.locator('.gunpla-detail h2').waitFor();
   pass('official four-photo product retains every gallery original and real missing CNY price',await p.locator('.gunpla-thumbnails button').count()===4&&await p.locator('.gunpla-facts').textContent().then(t=>t.includes('未公布')&&t.includes('1,760日元(含税)')&&t.includes('2026年8月')));
   pass('detail has no source or unrelated content links',await p.locator('#detail-root a').count()===0&&!/来源|适合年龄/.test(await p.locator('#detail-root').textContent()));
   await p.locator('[data-photo="1"]').click();await p.waitForFunction(()=>{const i=document.querySelector('.gunpla-gallery-hero img');return i.complete&&i.naturalWidth>0;},{},{timeout:120000});
   const original=await p.locator('.gunpla-gallery-hero img').evaluate(img=>img.src);await p.locator('.gunpla-gallery-hero img').click();
   pass('selected angle opens its corresponding full original',await p.locator('#image-viewer').isVisible()&&await p.locator('#enlarged-image').getAttribute('src')===original);
   await p.locator('#image-zoom-in').click();await p.locator('#image-zoom-in').click();pass('viewer zoom controls work',await p.locator('#image-scale').textContent()==='200%');await p.keyboard.press('Escape');
   pass('viewer escape keeps product detail open',!await p.locator('#image-viewer').isVisible()&&await p.locator('#detail-dialog').isVisible());
   await p.screenshot({path:out+'/gunpla-detail-'+profile.name+(local?'-local':'')+'.png'});
   await p.reload({waitUntil:'domcontentloaded'});await p.locator('.gunpla-detail h2').waitFor();await p.locator('#close-detail').click();await p.waitForFunction(y=>Math.abs(scrollY-y)<=3,before.y,{timeout:15000});await ready(p);
   pass('detail reload and close preserve page size page filters records and exact position',shape(await snapshot(p))===shape(before));
   await p.evaluate(()=>GunplaPage.openProduct('3027'));await p.locator('.gunpla-detail h2').waitFor();
   pass('second official product retains ten photos and both actual prices',await p.locator('.gunpla-thumbnails button').count()===10&&await p.locator('.gunpla-facts').textContent().then(t=>t.includes('60元')&&t.includes('1,100日元(含税)')&&t.includes('2025年10月')));
   await p.waitForFunction(()=>{const e=document.getElementById('detail-root');return e.scrollHeight-e.clientHeight>200;},{},{timeout:120000});
   const closeBefore=await p.locator('#close-detail').boundingBox();
   await p.locator('.gunpla-detail h2').click();pass('clicking inside detail keeps it open',await p.locator('#detail-dialog').isVisible());
   for(const photo of await p.locator('.photo-grid img').all()){
    await photo.scrollIntoViewIfNeeded();await photo.evaluate(img=>img.decode());
   }
   await p.locator('#detail-root').evaluate(e=>{e.scrollTop=e.scrollHeight;});await settled(p);
   pass('long photo gallery scrolls inside the detail panel',await p.locator('#detail-root').evaluate(e=>e.scrollTop>200&&e.scrollHeight>e.clientHeight));
   const closeAfter=await p.locator('#close-detail').boundingBox(),dialogBox=await p.locator('#detail-dialog').boundingBox();
   pass('close control stays at the visible panel corner after scrolling',closeAfter.y>=dialogBox.y&&closeAfter.y+closeAfter.height<=dialogBox.y+dialogBox.height&&Math.abs(closeAfter.y-closeBefore.y)<2&&Math.abs(closeAfter.x-closeBefore.x)<2);
   await p.screenshot({path:out+'/gunpla-detail-scrolled-'+profile.name+(local?'-local':'')+'.png'});
   await p.locator('#close-detail').click();await p.waitForFunction(y=>!document.querySelector('#detail-dialog').open&&Math.abs(scrollY-y)<=3,before.y);
   pass('close control works at gallery bottom and preserves list position',shape(await snapshot(p))===shape(before)&&!new URL(p.url()).hash);
   await p.evaluate(()=>GunplaPage.openProduct('3027'));await p.locator('.gunpla-detail h2').waitFor();
   pass('reopened detail begins at its first photo',await p.locator('#detail-root').evaluate(e=>e.scrollTop===0));
   await p.locator('#detail-root').evaluate(e=>{e.scrollTop=e.scrollHeight;});
   if(profile.name==='mobile')await p.touchscreen.tap(2,2);else await p.mouse.click(2,2);
   await p.waitForFunction(y=>!document.querySelector('#detail-dialog').open&&Math.abs(scrollY-y)<=3,before.y);
   pass('backdrop click closes detail and preserves filters page records and exact position',shape(await snapshot(p))===shape(before)&&!new URL(p.url()).hash);
   await p.locator('#gunpla-reset').click();await p.waitForFunction(()=>!GunplaPage.state.loading&&GunplaPage.state.query.limit===20);await p.evaluate(()=>scrollTo(0,0));
   pass('layout has no horizontal overflow',await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));await p.screenshot({path:out+'/gunpla-home-'+profile.name+(local?'-local':'')+'.png',fullPage:profile.name==='desktop'});
   report.profiles.push({name:profile.name,status:'pass'});await c.close();
  }finally{await browser.close();}
 }
 check('normal catalog browsing is not rate limited',report.rateLimited.length===0);check('no JavaScript errors',report.errors.length===0);report.status='pass';console.log(JSON.stringify({status:report.status,checks:report.checks.length,profiles:report.profiles}));
})().catch(error=>{report.errors.push(String(error.message).split('\n')[0]);console.error(String(error.message).split('\n')[0]);process.exitCode=1;}).finally(()=>fs.writeFileSync(out+'/gunpla-'+(local?'local':'public')+'.json',JSON.stringify(report,null,2)));
