const fs=require('node:fs');const path=require('node:path');const assert=require('node:assert/strict');const {chromium}=require('playwright');
async function main(){
 const output=path.resolve('artifacts/acceptance');fs.mkdirSync(output,{recursive:true});
 const base=process.env.PREVIEW_URL||'http://127.0.0.1:8092';const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe'});
 const report={status:'fail',assertions:0,base_url:base,errors:[]};
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1050},deviceScaleFactor:1});page.on('pageerror',e=>report.errors.push(e.message));
  let ready=false;for(let attempt=0;attempt<30;attempt++){try{const response=await page.request.get(base+'/health/ready',{timeout:2000});if(response.ok()){ready=true;break;}}catch(_){}await new Promise(resolve=>setTimeout(resolve,500));}assert.ok(ready,'API must be ready before browser navigation');
  await page.goto(base+'/preview/',{waitUntil:'domcontentloaded'});await page.locator('.catalog-card').first().waitFor();
  await page.waitForFunction(()=>{const i=document.querySelector('.catalog-card img');return i&&i.complete&&i.naturalWidth>0;},null,{timeout:60000});
  assert.ok(await page.locator('.catalog-card').count());report.assertions++;
  await page.screenshot({path:path.join(output,'desktop-overview.png')});await page.screenshot({path:path.join(output,'desktop-tomica.png'),fullPage:true});
  await page.locator('#brand option').nth(1).waitFor({state:'attached'});const brands=await page.locator('#brand option').allTextContents();assert.ok(brands.length>1);report.assertions++;
  const filtered=page.waitForResponse(response=>response.url().includes('/api/tomica?')&&response.url().includes('brand=')&&response.status()===200);await page.selectOption('#brand',{label:brands[1]});await filtered;await page.locator('.catalog-card').first().waitFor();assert.ok(await page.locator('.catalog-card').count());report.assertions++;
  await page.locator('.catalog-card').first().click();await page.locator('.detail-content h2').waitFor();assert.ok(await page.locator('#detail-dialog').isVisible());report.assertions++;
  await page.screenshot({path:path.join(output,'desktop-tomica-detail.png')});await page.locator('#close-detail').click();
  await page.locator('[data-kind="pokemon"]').click();await page.locator('#catalog-title').filter({hasText:'探索宝可梦'}).waitFor();await page.locator('.catalog-card').first().waitFor();
  await page.waitForFunction(()=>Array.from(document.querySelectorAll('.catalog-card img')).slice(0,3).every(i=>i.complete&&i.naturalWidth>0)&&document.querySelectorAll('.catalog-card img').length>=3,null,{timeout:60000});
  await page.screenshot({path:path.join(output,'desktop-pokemon.png'),fullPage:true});
  await page.locator('#search').fill('六尾');await page.waitForTimeout(700);await page.locator('.catalog-card').filter({hasText:'六尾'}).first().waitFor();await page.locator('.catalog-card').first().click();await page.locator('.detail-content h2').filter({hasText:'六尾'}).waitFor();
  const regional=page.getByRole('button',{name:'阿罗拉六尾',exact:true});if(await regional.count()){await regional.click();assert.ok(await page.locator('.detail-tags').textContent().then(v=>v.includes('冰')));report.assertions++;}
  await page.waitForFunction(()=>{const i=document.querySelector('.detail-visual img');return i&&i.complete&&i.naturalWidth>0;},null,{timeout:60000});
  await page.screenshot({path:path.join(output,'desktop-pokemon-detail.png')});await page.locator('#close-detail').click();
  await page.setViewportSize({width:390,height:844});await page.locator('#reset').click();await page.locator('.catalog-card').first().waitFor();await page.screenshot({path:path.join(output,'mobile-overview.png')});await page.screenshot({path:path.join(output,'mobile-pokemon.png'),fullPage:true});
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth);assert.equal(overflow,false);report.assertions++;
  await page.locator('[data-kind="tomica"]').click();await page.locator('.catalog-card').first().waitFor();await page.screenshot({path:path.join(output,'mobile-tomica.png'),fullPage:true});
  await page.locator('#search').fill('this-will-not-exist-98765');await page.locator('#feedback').filter({hasText:'没有找到'}).waitFor();assert.equal(await page.locator('.catalog-card').count(),0);assert.match(await page.locator('#feedback').textContent(),/没有找到/);report.assertions++;
  assert.deepEqual(report.errors,[]);report.assertions++;report.status='pass';
 }finally{await browser.close();fs.writeFileSync(path.join(output,'browser-preview.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));}
}
main().catch(error=>{console.error(error.stack);process.exitCode=1;});
