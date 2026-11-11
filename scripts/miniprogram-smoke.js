const fs=require('node:fs');const path=require('node:path');const assert=require('node:assert/strict');
async function main(){
  const mode=process.argv.includes('production')?'production':'demo';const root=path.resolve(__dirname,'..');const output=path.join(root,'artifacts/acceptance');fs.mkdirSync(output,{recursive:true});
  const result={mode,status:'blocked',timestamp:new Date().toISOString(),assertions:0};let program;
  try{
    if(!process.env.WECHAT_CLI_PATH||!fs.existsSync(process.env.WECHAT_CLI_PATH))throw Object.assign(new Error('WeChat developer tool CLI not configured'),{blocked:true});
    const automator=require('miniprogram-automator');
    program=await automator.launch({cliPath:process.env.WECHAT_CLI_PATH,projectPath:path.join(root,mode==='production'?'artifacts/miniprogram':'miniprogram')});
    for(const kind of ['tomica','pokemon']){
      let page=await program.reLaunch('/pages/'+kind+'-list/index');await page.waitFor('.card');const cards=await page.$$('.card');assert.ok(cards.length);result.assertions++;
      await program.screenshot({path:path.join(output,'wechat-'+kind+'-list.png')});await cards[0].tap();page=await program.currentPage();await page.waitFor('.detail-name');assert.ok(await page.$('.detail-name'));result.assertions++;
      await program.screenshot({path:path.join(output,'wechat-'+kind+'-detail.png')});
    }
    if(mode==='production'){const manifest=JSON.parse(fs.readFileSync(path.join(root,'artifacts/miniprogram-manifest.json'),'utf8'));result.build_hash=manifest.build_hash;result.appid=manifest.appid;result.api_domain=manifest.api_domain;}
    result.status='pass';process.exitCode=0;
  }catch(error){result.status=error.blocked?'blocked':'fail';result.error=error.message;process.exitCode=error.blocked?2:1;}
  finally{if(program)await program.close();fs.writeFileSync(path.join(output,'wechat-'+mode+'.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));}
}
main().catch(error=>{console.error(error.message);process.exitCode=1;});
