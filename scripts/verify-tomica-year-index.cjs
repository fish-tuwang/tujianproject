const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 const car={id:1,number:'001',name:'年份测试车型',brand:'Toyota',release_year:1970,variants:[]};
 await page.route('http://atlas.test/**',async route=>{
  const u=new URL(route.request().url());
  if(u.pathname.startsWith('/api/')){
   let data={items:[],total:0,next_cursor:null};
   if(u.pathname==='/api/auth/me')data={auth_enabled:false};
   else if(u.pathname==='/api/tomica/filters')data={brands:['Toyota'],years:Array.from({length:57},(_,i)=>1970+i),unknown_year:true};
   else if(u.pathname==='/api/tomica')data={items:[{...car,release_year:Number(u.searchParams.get('year'))||1970}],total:1,page:Number(u.searchParams.get('page'))||1,total_pages:1};
   else if(u.pathname==='/api/tomica/1')data=car;
   else if(u.pathname==='/api/pokemon/regions')data={items:[]};
   return route.fulfill({json:data});
  }
  const file=path.join('backend',u.pathname==='/preview/'?'preview/index.html':u.pathname);
  if(fs.existsSync(file))return route.fulfill({path:file});
  return route.fulfill({status:404,body:''});
 });
 const ready=()=>page.waitForFunction(()=>!state.loading&&document.querySelectorAll('#year-tabs button').length===59);
 await page.goto('http://atlas.test/preview/?catalog=tomica');await ready();
 assert.equal(await page.locator('#year').count(),0);
 await page.locator('[data-year="1971"]').click();await page.waitForFunction(()=>!state.loading&&state.items[0]?.release_year===1971);
 assert.equal(await page.locator('[data-year="1971"]').getAttribute('aria-pressed'),'true');
 console.log('PASS direct year index filters cars and highlights selected year');
 await page.locator('#brand').selectOption('Toyota');await page.waitForFunction(()=>!state.loading&&state.query.brand==='Toyota');assert.equal(await page.evaluate(()=>state.query.year),'1971');
 await page.locator('#search').fill('Toyota');await page.waitForFunction(()=>!state.loading&&state.query.q==='Toyota');assert.equal(await page.evaluate(()=>state.query.year),'1971');
 console.log('PASS year combines with brand and search');
 await page.reload();await ready();assert.equal(await page.locator('[data-year="1971"]').getAttribute('aria-pressed'),'true');
 await page.locator('.catalog-card').first().click();await page.locator('#detail-dialog').waitFor({state:'visible'});await page.locator('#close-detail').click();assert.equal(await page.evaluate(()=>state.query.year),'1971');
 console.log('PASS refresh and detail return preserve selected year');
 const aligned=()=>page.locator('#year-tabs').evaluate(nav=>{
  const boxes=[...nav.children].map(b=>({width:b.getBoundingClientRect().width,top:b.offsetTop,left:b.offsetLeft}));
  const rows=[...new Set(boxes.map(b=>b.top))];
  return boxes.every(b=>Math.abs(b.width-boxes[0].width)<1)&&rows.every(top=>Math.abs(boxes.find(b=>b.top===top).left-boxes[0].left)<1);
 });
 assert(await aligned());console.log('PASS desktop years have equal widths and aligned columns');

 await page.locator('#year-panel').screenshot({path:'artifacts/acceptance/tomica-year-index-desktop.png'});
 await page.setViewportSize({width:390,height:844});await page.locator('#year-panel').scrollIntoViewIfNeeded();
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 assert(await aligned());console.log('PASS mobile year columns align without overflow');
 await page.locator('#year-panel').screenshot({path:'artifacts/acceptance/tomica-year-index-mobile.png'});
 await page.locator('[data-year=""]').click();await page.waitForFunction(()=>!state.loading&&!state.query.year);
 await page.locator('[data-kind="pokemon"]').click();await page.waitForFunction(()=>!state.loading&&state.kind==='pokemon');assert.equal(await page.locator('#year-panel').isVisible(),false);
 assert.deepEqual(errors,[]);console.log('PASS mobile layout, all-years reset and Pokemon isolation; no runtime errors');
 await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
