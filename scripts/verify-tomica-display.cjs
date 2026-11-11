const browserAuth=require('./browser-auth.cjs');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
async function main(){
  const base=process.env.PREVIEW_URL||'https://117.72.11.77',local=process.argv.includes('--local'),output=path.resolve('artifacts/acceptance');
  const report={status:'fail',mode:local?'local frontend with live read-only API':'deployed public frontend',assertions:0,checks:[],errors:[]};
  const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  const page=await browser.newPage({viewport:{width:1440,height:1050},...browserAuth.contextOptions()});page.on('pageerror',e=>report.errors.push(e.message));
  if(local)await page.route('**/preview/**',async route=>{const file=new URL(route.request().url()).pathname.split('/').pop()||'index.html';if(['index.html','app.js','pokemon-details.js','style.css','auth-client.js'].includes(file))await route.fulfill({path:path.resolve('backend/preview',file),contentType:file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html'});else await route.continue();});
  const check=(name,value)=>{assert.ok(value,name);report.assertions++;report.checks.push(name);console.log('PASS '+name);};
  const centered=async(parent,child)=>page.locator(parent).evaluate((p,selector)=>{const a=p.getBoundingClientRect(),b=p.querySelector(selector).getBoundingClientRect();return Math.abs(a.x+a.width/2-b.x-b.width/2)<.6&&Math.abs(a.y+a.height/2-b.y-b.height/2)<.6;},child);
  const loaded=async selector=>page.waitForFunction(selector=>{const i=document.querySelector(selector);return i&&i.complete&&i.naturalWidth>0;},selector,{timeout:90000});
  try{
    if(!local){
      const expected=await(await page.request.get(base+'/api/tomica?q='+encodeURIComponent('マークX')+'&limit=100&page=1')).json();
      for(const q of ['Mark x','MARKX','ＭＡＲＫ　Ｘ','マーク X','丰田 Mark-X','Mark X Toyota','锐志']){
        const r=await page.request.get(base+'/api/tomica?'+new URLSearchParams({q,limit:100,page:1}));const result=await r.json();
        check('search '+q+' matches the actual Japanese Mark X records',r.ok()&&result.total>=4&&result.items.some(i=>i.number==='072')&&result.items.every(i=>i.name_original.normalize('NFKC').replace(/\s/g,'').toLowerCase().includes('マークx'))&&JSON.stringify(result.items.map(i=>i.id).sort())===JSON.stringify(expected.items.map(i=>i.id).sort()));
      }
      const none=await(await page.request.get(base+'/api/tomica?'+new URLSearchParams({q:'Mark X',brand:'Honda',page:1}))).json();check('brand filter still excludes Toyota from Honda',none.total===0);
      for(const q of ['トヨ','シビ']){const result=await(await page.request.get(base+'/api/tomica?'+new URLSearchParams({q,limit:100,page:1}))).json();check('partial original name '+q+' remains searchable',result.total>0&&result.items.some(i=>i.name_original.normalize('NFKC').includes(q)));}
    }
    await page.goto(base+'/preview/?catalog=tomica&v=0.4.0',{waitUntil:'domcontentloaded'});
    await page.waitForFunction(()=>!state.loading&&state.items.length===20);await loaded('.catalog-card img');
    check('five columns and twenty cards remain',await page.locator('.catalog-card').count()===20&&await page.locator('#cards').evaluate(e=>getComputedStyle(e).gridTemplateColumns.split(' ').length===5));
    check('photo fills its frame and reaches card borders',await page.locator('.catalog-card').first().evaluate(card=>{const frame=card.querySelector('.card-art'),img=frame.querySelector('img'),a=card.getBoundingClientRect(),b=frame.getBoundingClientRect(),c=img.getBoundingClientRect();return Math.abs(b.left-a.left-1)<1&&Math.abs(a.right-b.right-1)<1&&Math.abs(b.top-a.top-1)<1&&Math.abs(b.width-c.width)<1&&Math.abs(b.height-c.height)<1&&getComputedStyle(img).objectFit==='cover'&&getComputedStyle(frame,'::before').display==='none';}));
    check('brand diamond is centered inside its tile',await centered('.brand-icon','svg'));
    await page.waitForFunction(()=>[...document.querySelectorAll('.catalog-card img')].slice(0,5).every(i=>i.naturalWidth>0&&getComputedStyle(i).opacity==='1'),null,{timeout:90000});
    await page.screenshot({path:output+'/tomica-filled-cards.png'});
    const q=local?'マークX':'Mark x';const response=page.waitForResponse(r=>r.url().includes('/api/tomica?')&&new URL(r.url()).searchParams.get('q')===q&&r.status()===200);
    await page.locator('#search').fill(q);const result=await(await response).json();await page.waitForFunction(({q,ids})=>!state.loading&&state.query.q===q&&JSON.stringify(state.items.map(i=>i.id))===JSON.stringify(ids),{q,ids:result.items.map(i=>i.id)});
    check('search control returns the requested cars on page one',await page.evaluate(()=>state.page===1&&state.items.some(i=>i.number==='064')));
    await page.waitForFunction(()=>[...document.querySelectorAll('.catalog-card img')].every(i=>i.naturalWidth>0&&getComputedStyle(i).opacity==='1'),null,{timeout:90000});
    await page.screenshot({path:output+'/tomica-mark-x-search.png'});
    await page.locator('.catalog-card').filter({has:page.locator('.card-number',{hasText:'No. 064'})}).click();
    await page.locator('.detail-content h2').filter({hasText:'マークX'}).waitFor();await loaded('#detail-root .detail-visual img');
    check('detail close symbol is geometrically centered',await centered('#close-detail','svg'));
    const original=await page.locator('#detail-root .detail-visual img').evaluate(i=>i.src);const detailURL=page.url();
    await page.locator('#detail-root .detail-visual img').click();await loaded('#enlarged-image');
    check('main picture opens the same original in the viewer',await page.locator('#image-viewer').isVisible()&&await page.locator('#enlarged-image').getAttribute('src')===original);
    check('large picture preserves its full aspect ratio',await page.locator('#enlarged-image').evaluate(i=>getComputedStyle(i).objectFit==='contain'));
    check('fit view keeps the entire picture inside its viewport',await page.locator('#enlarged-image').evaluate(i=>{const a=i.getBoundingClientRect(),b=document.getElementById('image-stage').getBoundingClientRect();return a.left>=b.left-1&&a.right<=b.right+1&&a.top>=b.top-1&&a.bottom<=b.bottom+1;}));
    await page.locator('#image-zoom-in').click();await page.locator('#image-zoom-in').click();check('zoom controls enlarge to two hundred percent',(await page.locator('#image-scale').textContent())==='200%');
    await page.locator('#image-reset').click();check('reset returns to fit view',(await page.locator('#image-scale').textContent())==='100%');
    check('viewer close symbol is centered',await centered('#close-image','svg'));await page.locator('#image-viewer').screenshot({path:output+'/tomica-image-viewer.png'});
    await page.keyboard.press('Escape');check('Escape closes only the large picture',!await page.locator('#image-viewer').isVisible()&&await page.locator('#detail-dialog').isVisible()&&page.url()===detailURL);
    const version=page.locator('.version-photo img').first();await version.scrollIntoViewIfNeeded();await loaded('.version-photo img');const versionURL=await version.evaluate(i=>i.src);await version.click();await loaded('#enlarged-image');check('version picture opens its own original',await page.locator('#enlarged-image').getAttribute('src')===versionURL);await page.locator('#close-image').click();
    await page.setViewportSize({width:390,height:844});await page.locator('#detail-root .detail-visual img').click();await loaded('#enlarged-image');
    check('mobile viewer fits without document overflow',await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth&&document.querySelector('#image-viewer').getBoundingClientRect().width<=innerWidth));
    await page.locator('#image-viewer').screenshot({path:output+'/tomica-image-viewer-mobile.png'});await page.locator('#close-image').click();
    check('mobile close symbol remains centered',await centered('#close-detail','svg'));await page.locator('#close-detail').click();
    check('return preserves the car catalog and its search',await page.evaluate(()=>state.kind==='tomica'&&state.query.q.length>0)&&!await page.locator('#type-wrap').isVisible());
    check('no JavaScript runtime errors',report.errors.length===0);report.status='pass';
  }finally{await browser.close();fs.writeFileSync(output+'/tomica-display-'+(local?'local':'public')+'.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report));}
}
main().catch(error=>{console.error(error.stack);process.exitCode=1;});
