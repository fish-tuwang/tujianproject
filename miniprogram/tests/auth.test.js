const test=require('node:test'),assert=require('node:assert/strict');
const session=require('../services/session');
const {createApi}=require('../services/api');
const {loadPrivateImage}=require('../services/private-images');
const {createListPage,createDetailPage}=require('../lib/page-factory');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const profile=letter=>({access_token:letter.repeat(43),username:'owner',expires_at:2000000000,must_change_password:false});
function runtime(){const values=new Map(),launches=[];return {values,launches,getStorageSync:k=>values.get(k),setStorageSync:(k,v)=>values.set(k,v),removeStorageSync:k=>values.delete(k),reLaunch:o=>launches.push(o.url)};}
function page(definition){return {...definition,data:structuredClone(definition.data),setData(value){Object.assign(this.data,value);}};}

test('API sends the current bearer and JSON client header without putting passwords in URLs',async()=>{
 const wx=runtime(),requests=[];wx.request=o=>{requests.push(o);queueMicrotask(()=>o.success({statusCode:200,data:{items:[]}}));return{abort(){}};};
 session.save(wx,profile('A'));const api=createApi(wx,'https://catalog.test');await api.list('pokemon');
 assert.equal(requests[0].header.Authorization,'Bearer '+'A'.repeat(43));session.save(wx,profile('B'));await api.login('owner','private-test-password');
 assert.equal(requests[1].header['X-Catalog-Client'],'miniprogram');assert.equal(requests[1].header.Authorization,'Bearer '+'B'.repeat(43));assert.ok(!requests[1].url.includes('private-test-password'));assert.equal(requests[1].data.password,'private-test-password');
});

test('a late 401 from an old token cannot sign out a newer login',async()=>{
 const wx=runtime();let pending;wx.request=o=>{pending=o;return{abort(){}};};session.save(wx,profile('A'));const call=createApi(wx,'https://catalog.test').me();session.save(wx,profile('B'));pending.success({statusCode:401,data:{code:'AUTH_REQUIRED'}});await assert.rejects(call);assert.equal(session.token(wx),'B'.repeat(43));assert.equal(wx.launches.length,0);
});

test('401 clears once and an incorrect current password does not clear a valid session',async()=>{
 const wx=runtime();session.save(wx,profile('A'));wx.request=o=>{queueMicrotask(()=>o.success({statusCode:403,data:{code:'INVALID_CURRENT_PASSWORD',message:'当前密码错误'}}));return{abort(){}};};const api=createApi(wx,'https://catalog.test');await assert.rejects(api.changePassword('incorrect','a sufficiently long password'));assert.ok(session.token(wx));
 wx.request=o=>{queueMicrotask(()=>o.success({statusCode:401,data:{code:'AUTH_REQUIRED'}}));return{abort(){}};};await assert.rejects(api.me());await assert.rejects(api.me());assert.equal(session.token(wx),'');assert.equal(wx.launches.length,1);
});

test('private image downloads deduplicate and stay within three concurrent requests',async()=>{
 const wx=runtime(),calls=[];session.save(wx,profile('A'));wx.downloadFile=o=>{calls.push(o);return{};};
 const first=loadPrivateImage(wx,'https://catalog.test','https://catalog.test/api/reference-images/a');assert.equal(first,loadPrivateImage(wx,'https://catalog.test','https://catalog.test/api/reference-images/a'));
 const values=[first,...['b','c','d','e'].map(x=>loadPrivateImage(wx,'https://catalog.test','https://catalog.test/api/reference-images/'+x))];assert.equal(calls.length,3);
 for(let i=0;i<5;i++){assert.ok(calls[i]);assert.equal(calls[i].header.Authorization,'Bearer '+'A'.repeat(43));calls[i].success({statusCode:200,tempFilePath:'wxfile://'+i});await tick();}
 assert.deepEqual(await Promise.all(values),['wxfile://0','wxfile://1','wxfile://2','wxfile://3','wxfile://4']);const before=calls.length;assert.equal(await loadPrivateImage(wx,'https://catalog.test','https://s1.52poke.com/public.png'),'https://s1.52poke.com/public.png');assert.equal(calls.length,before);
});

test('a downloaded image from the old generation cannot populate a new login cache',async()=>{
 const wx=runtime(),calls=[];wx.downloadFile=o=>{calls.push(o);};session.save(wx,profile('A'));const old=loadPrivateImage(wx,'https://catalog.test','/api/reference-images/p');session.save(wx,profile('B'));calls[0].success({statusCode:200,tempFilePath:'wxfile://old'});await assert.rejects(old,e=>e.code==='STALE_SESSION');await tick();const fresh=loadPrivateImage(wx,'https://catalog.test','/api/reference-images/p');assert.equal(calls.length,2);calls[1].success({statusCode:200,tempFilePath:'wxfile://fresh'});assert.equal(await fresh,'wxfile://fresh');
});

test('old list responses and onHide cannot restore a previous account cache',async()=>{
 const wx=runtime(),pending=[];session.save(wx,profile('A'));wx.request=o=>{if(o.url.endsWith('/regions'))queueMicrotask(()=>o.success({statusCode:200,data:{items:[]}}));else pending.push(o);return{abort(){}};};
 const old=page(createListPage('pokemon',wx));old.onLoad();session.save(wx,profile('B'));old.onHide();old.onUnload();pending[0].success({statusCode:200,data:{items:[{id:'old',dex:1,name_zh:'old'}],next_cursor:null}});await tick();
 const fresh=page(createListPage('pokemon',wx));fresh.onLoad();assert.equal(fresh.data.items.length,0);pending[1].success({statusCode:200,data:{items:[{id:'new',dex:906,name_zh:'new'}],next_cursor:null}});await tick();assert.equal(fresh.data.items[0].dex,906);fresh.onUnload();
});

test('protected original gallery previews use local authenticated downloads',async()=>{
 let preview;const p=page(createDetailPage('tomica'));p.alive=true;p.wxApi={previewImage:o=>preview=o};p.api={downloadImage:url=>Promise.resolve('wxfile://'+url.split('/').pop())};p.data.detail={image_url:'https://catalog.test/api/reference-images/main',variants:[{image_url:'https://catalog.test/api/reference-images/version'}]};await p.previewImage({currentTarget:{dataset:{url:p.data.detail.variants[0].image_url}}});assert.deepEqual(preview,{current:'wxfile://version',urls:['wxfile://main','wxfile://version']});
});

test('failed logout retains the valid account and presents a retryable error',async()=>{
 const wx=runtime();session.save(wx,profile('A'));const p=page(createListPage('tomica'));p.alive=true;p.wxApi=wx;p.api={logout:()=>Promise.reject(new Error('连接失败'))};await p.logout();assert.equal(session.token(wx),'A'.repeat(43));assert.equal(wx.launches.length,0);assert.equal(p.data.error,'连接失败');assert.equal(p.data.logoutPending,false);
});
