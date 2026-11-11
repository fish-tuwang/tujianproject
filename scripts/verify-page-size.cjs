const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
(async()=>{
 const local=process.argv.includes('--local'),report={status:'fail',mode:local?'local frontend, live read-only API':'public',assertions:0,checks:[],errors:[]};
 const check=(name,value)=>{assert.ok(value,name);report.assertions++;report.checks.push(name);console.log('PASS '+name);};
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
 const p=await browser.newPage({viewport:{width:1440,height:1050}});p.on('pageerror',e=>report.errors.push(e.message));
 if(local)await p.route('**/preview/**',async route=>{const file=new URL(route.request().url()).pathname.split('/').pop()||'index.html';if(['index.html','app.js','pokemon-details.js','style.css'].includes(file))await route.fulfill({path:path.resolve('backend/preview',file)});else await route.continue();});
 const data=async(page,size,action)=>{const response=p.waitForResponse(r=>{const u=new URL(r.url());return u.pathname==='/api/tomica'&&u.searchParams.get('page')===String(page)&&u.searchParams.get('limit')===String(size)&&r.status()===200;});await action();const value=await(await response).json();await p.waitForFunction(({page,size})=>!state.loading&&state.page===page&&state.pageSize===size,{page,size});return value;};
 try{
  await p.goto('http://117.72.11.77/preview/?catalog=tomica&v=0.5.1',{waitUntil:'domcontentloaded'});
  await p.waitForFunction(()=>!state.loading&&state.items.length===20);
  check('initial page defaults to twenty',await p.locator('#page-size').inputValue()==='20'&&await p.locator('.catalog-card').count()===20);
  for(const size of [40,60,100]){
   const result=await data(1,size,()=>p.locator('#page-size').selectOption(String(size)));
   check(size+' cards with matching total pages',await p.locator('.catalog-card').count()===size&&result.total_pages===Math.ceil(result.total/size));
   const first=result.items.map(i=>i.id),next=await data(2,size,()=>p.locator('#next-page').click());
   check(size+' next page replaces without overlap',await p.locator('.catalog-card').count()===size&&!next.items.some(i=>first.includes(i.id)));
  }
  const filtered=await data(1,100,()=>p.locator('#brand').selectOption('Toyota'));
  check('brand filter keeps size and resets page',filtered.page===1&&filtered.items.length===100&&filtered.items.every(i=>i.brand==='Toyota'));
  await data(1,40,()=>p.locator('#page-size').selectOption('40'));
  check('changing size retains the brand filter',await p.evaluate(()=>state.query.brand==='Toyota'&&state.items.every(i=>i.brand==='Toyota')));
  const lastPage=await p.evaluate(()=>state.totalPages);
  await p.locator('#page-jump-input').fill(String(lastPage));
  const last=await data(lastPage,40,()=>p.locator('#page-jump button').click());
  check('last page remainder uses selected size',last.items.length===last.total-(lastPage-1)*40&&await p.locator('#next-page').isDisabled());
  await data(1,40,()=>p.locator('#reset').click());
  check('reset clears filters while keeping chosen size',await p.evaluate(()=>!Object.keys(state.query).length&&state.items.length===40));
  const search=await data(1,40,()=>p.locator('#search').fill('Mark x'));
  check('Mark X search still returns the four matching cars',search.total===4);
  await p.locator('.catalog-card').first().click();await p.waitForFunction(()=>state.detail&&document.querySelector('#detail-dialog').open);
  check('details stay open after changing size and searching',await p.locator('#detail-dialog').isVisible());
  await p.locator('#close-detail').click();
  await p.locator('[data-kind="pokemon"]').click();await p.waitForFunction(()=>state.kind==='pokemon'&&!state.loading&&state.items.length===12);
  check('Pokemon list stays separate with twelve and no page-size control',!await p.locator('#page-size').isVisible()&&!await p.locator('#brand-wrap').isVisible());
  await p.locator('[data-kind="tomica"]').click();await p.waitForFunction(()=>state.kind==='tomica'&&!state.loading&&state.items.length===40);
  await data(1,20,()=>p.locator('#page-size').selectOption('20'));
  const positions=await p.locator('.catalog-card').evaluateAll(nodes=>nodes.map(n=>{const r=n.getBoundingClientRect();return [Math.round(r.x),Math.round(r.y)];}));
  check('twenty restores five columns and four rows',new Set(positions.map(r=>r[0])).size===5&&new Set(positions.map(r=>r[1])).size===4);
  await p.locator('#page-size').scrollIntoViewIfNeeded();await p.screenshot({path:'artifacts/acceptance/page-size-'+(local?'local':'public')+'.png'});
  await p.setViewportSize({width:390,height:844});
  check('page-size selector fits mobile width',await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  check('no JavaScript errors',report.errors.length===0);report.status='pass';
 }catch(error){console.log('UI_STATE '+JSON.stringify(await p.evaluate(()=>({page:state.page,size:state.pageSize,loading:state.loading,query:state.query,select:document.getElementById('page-size').value,feedback:document.getElementById('feedback').textContent}))));throw error;}finally{await browser.close();fs.writeFileSync('artifacts/acceptance/page-size-'+(local?'local':'public')+'.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report));}
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
