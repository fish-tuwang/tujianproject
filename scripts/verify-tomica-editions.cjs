const assert=require('node:assert/strict'),fs=require('node:fs');
const {chromium}=require('playwright');
(async()=>{
 const base='http://117.72.11.77',report={status:'fail',checks:[],errors:[]};
 const check=(name,value)=>{assert.ok(value,name);report.checks.push(name);console.log('PASS '+name);};
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
 try{
  const context=await browser.newContext({viewport:{width:1440,height:1000}}),page=await context.newPage();
  page.on('pageerror',e=>report.errors.push(e.message));
  let ids;
  for(const q of ['面包小偷','麵包小偷','パンどろぼう','Bread Thief','Pandorobou']){
   const response=await page.request.get(base+'/api/tomica?'+new URLSearchParams({q,page:1,limit:100}));assert.equal(response.status(),200);
   const body=await response.json(),found=body.items.filter(i=>i.source_locator.startsWith('edition:'));
   check('search finds original edition: '+q,found.length>0);
   const current=found.map(i=>i.id).sort();if(ids)assert.deepEqual(current,ids);else ids=current;
  }
  const detail=await(await page.request.get(base+'/api/tomica/'+ids[0])).json();
  const numbered=await(await page.request.get(base+'/api/tomica?'+new URLSearchParams({q:'114',page:1,limit:100}))).json();
  check('number search never matches an internal edition fingerprint',numbered.items.length>0&&numbered.items.every(i=>[i.number,i.name_original,i.name_display,i.brand,i.source_locator.startsWith('edition:')?'':i.source_locator].some(v=>String(v||'').normalize('NFKC').replace(/[^\p{L}\p{N}ー]/gu,'').includes('114'))));
  check('bread thief uses its exact source photograph',detail.source_image_url.endsWith('/event/IMG_9291.jpg')&&detail.name_original.startsWith('パンどろぼう'));
  check('detail preserves matching original and one own version',detail.variants.length===1&&detail.variants[0].source_image_url===detail.source_image_url);
  const image=await page.request.get(base+detail.preview_image_url);
  check('preloaded original is delivered from local cache',image.ok()&&['disk','redis'].includes(image.headers()['x-catalog-cache']));
  const again=await page.request.get(base+detail.preview_image_url,{headers:{'If-None-Match':image.headers().etag}});
  check('cached original supports conditional response',again.status()===304);
  await page.goto(base+'/preview/?catalog=tomica&v=0.8.0',{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>!state.loading&&state.items.length===20);
  await page.locator('#search').fill('面包小偷');await page.waitForFunction(()=>!state.loading&&state.query.q==='面包小偷'&&state.items.length>0);
  check('Chinese keyword displays corresponding edition',await page.locator('.card-name').first().textContent().then(t=>t.includes('パンどろぼう')));
  await page.locator('.catalog-card').first().click();await page.locator('.detail-content h2').filter({hasText:'パンどろぼう'}).waitFor();
  await page.waitForFunction(()=>{const i=document.querySelector('.detail-visual img');return i?.complete&&i.naturalWidth>0;});
  check('detail navigation displays a decoded original',await page.locator('#detail-dialog').isVisible());
  await page.screenshot({path:'artifacts/acceptance/tomica-bread-thief-detail.png'});
  await page.locator('.detail-visual img').click();await page.locator('#image-viewer').waitFor();
  check('edition photograph opens the image viewer',await page.locator('#image-viewer').isVisible());
  await page.locator('#close-image').click();await page.locator('#close-detail').click();
  check('closing the edition keeps its keyword results',await page.locator('#search').inputValue()==='面包小偷'&&await page.locator('.catalog-card').count()>0);
  await page.screenshot({path:'artifacts/acceptance/tomica-bread-thief-search.png'});
  for(const q of ['吉卜力','hololive','史努比']){
   const data=await(await page.request.get(base+'/api/tomica?'+new URLSearchParams({q,page:1,limit:100}))).json();
   check('other collaboration is indexed: '+q,data.items.some(i=>i.source_locator.startsWith('edition:')));
  }
  const mobile=await browser.newContext({viewport:{width:390,height:844},isMobile:true,hasTouch:true}),phone=await mobile.newPage();
  phone.on('pageerror',e=>report.errors.push(e.message));
  await phone.goto(base+'/preview/?catalog=tomica&v=0.8.0#tomica/'+ids[0],{waitUntil:'domcontentloaded'});
  await phone.locator('.detail-content h2').filter({hasText:'パンどろぼう'}).waitFor();
  check('mobile deep link opens the same collaboration detail',await phone.locator('#detail-dialog').isVisible());
  check('long edition title stays inside mobile viewport',await phone.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  await phone.waitForFunction(()=>{const i=document.querySelector('.detail-visual img');return i?.complete&&i.naturalWidth>0&&getComputedStyle(i).opacity==='1';});
  await phone.locator('.detail-visual img').tap();await phone.locator('#image-viewer').waitFor();
  check('mobile original enlarges on tap',await phone.locator('#image-viewer').isVisible());
  await phone.locator('#close-image').tap();await phone.locator('#close-detail').tap();
  check('mobile close keeps Tomica active',await phone.evaluate(()=>state.kind==='tomica'&&!document.getElementById('detail-dialog').open));
  await mobile.close();
  check('no JavaScript errors',!report.errors.length);report.status='pass';report.assertions=report.checks.length;
 }finally{await browser.close();fs.writeFileSync('artifacts/acceptance/tomica-editions-public.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report));}
})().catch(e=>{console.error(e.stack);process.exitCode=1;});
