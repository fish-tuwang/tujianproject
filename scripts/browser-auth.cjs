const fs=require('node:fs');
function contextOptions(){return process.env.CATALOG_AUTH_STATE?{storageState:process.env.CATALOG_AUTH_STATE}:{};}
function headers(url){
 if(!process.env.CATALOG_AUTH_STATE)return {};
 let state;try{state=JSON.parse(fs.readFileSync(process.env.CATALOG_AUTH_STATE,'utf8'));}catch(_){throw new Error('私有验收会话文件无法读取');}
 const target=new URL(url),now=Date.now()/1000;
 const values=(state.cookies||[]).filter(c=>{
  const domain=c.domain.replace(/^\./,''),path=c.path||'/';
  const domainMatches=target.hostname===domain||(c.domain.startsWith('.')&&target.hostname.endsWith('.'+domain));
  const pathMatches=target.pathname.startsWith(path)&&(path.endsWith('/')||target.pathname.length===path.length||target.pathname[path.length]==='/');
  return c.name==='catalog_session'&&/^[A-Za-z0-9_-]{43}$/.test(c.value)&&domainMatches&&pathMatches&&(!c.secure||target.protocol==='https:')&&(c.expires<0||c.expires>now);
 });
 return values.length?{Cookie:values.map(c=>c.name+'='+c.value).join('; ')}:{};
}
module.exports={contextOptions,headers};
