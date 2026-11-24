const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('backend/preview/app.js','utf8');
const code=source.slice(source.indexOf('const tomicaCoverCache'),source.indexOf('function renderCards()'));
const url='/api/tomica/official-images/'+'a'.repeat(64);
const product=(kind='packaging',status='verified')=>({packaging_status:status,images:[{kind,url}]});
function setup(detail,{fail=false}={}){
 let calls=0,active=0,peak=0;
 const state={kind:'tomica'};
 const context=vm.createContext({Date,Map,Promise,Array,Math,encodeURIComponent,state,
 request:async()=>{calls++;active++;peak=Math.max(peak,active);await new Promise(r=>setImmediate(r));active--;return detail;},
 Image:class{set src(value){this.url=value;queueMicrotask(()=>fail?this.onerror():this.onload());}}
 });
 vm.runInContext(code+';this.cover=packagingCover;this.load=loadTomicaCovers',context);
 return {context,state,calls:()=>calls,peak:()=>peak};
}
function card(){const art={added:[],removed:0,querySelector(){return {remove(){art.removed++;}};},prepend(image){this.added.push(image);}};return {isConnected:true,art,querySelector:()=>art};}
test('only verified packaging belonging to the model is eligible',()=>{
 const {context}=setup({});
 assert.equal(context.cover({official_products:[product()]}),url);
 for(const p of [product('gallery'),product('packaging','unverified'),{packaging_status:'verified',images:[{kind:'packaging',url:'https://other.example/box.jpg'}]}])assert.equal(context.cover({official_products:[p]}),null);
 assert.equal(context.cover({}),null);
});
test('box replaces card only; detail gallery stays intact; lookups cached',async()=>{
 const detail={official_products:[product()]},before=JSON.stringify(detail),{context,calls}=setup(detail),c=card(),item={id:'one',official_product_count:1,name_original:'car'};
 await context.load([item],[c]);await context.load([item],[c]);
 assert.equal(c.art.added[0].url,url);assert.equal(calls(),1);assert.equal(JSON.stringify(detail),before);
});
test('missing or failed box preserves existing car image',async()=>{
 for(const [detail,fail] of [[{},false],[{official_products:[product()]},true]]){
 const {context}=setup(detail,{fail}),c=card();await context.load([{id:'one',official_product_count:1}],[c]);assert.equal(c.art.removed,0);assert.equal(c.art.added.length,0);
 }
});
test('no official products and Pokemon cause no detail requests',async()=>{
 const {context,state,calls}=setup({});await context.load([{id:'one',official_product_count:0}],[card()]);state.kind='pokemon';await context.load([{id:'two',official_product_count:1}],[card()]);assert.equal(calls(),0);
});
test('bounded concurrency and detached pages are not updated',async()=>{
 const {context,peak}=setup({official_products:[product()]});const cards=Array.from({length:12},card),items=cards.map((_,i)=>({id:String(i),official_product_count:1}));
 const pending=context.load(items,cards);cards[0].isConnected=false;await pending;assert.ok(peak()<=4);assert.equal(cards[0].art.added.length,0);assert.equal(cards[1].art.added.length,1);
});
