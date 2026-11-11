'use strict';
const $ = id => document.getElementById(id);
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const types = ['一般','火','水','电','草','冰','格斗','毒','地面','飞行','超能力','虫','岩石','幽灵','龙','恶','钢','妖精'];
const catalogKinds = ['tomica', 'pokemon'];
const entryKind = new URLSearchParams(location.search).get('catalog');
const initialHashKind = location.hash.slice(1).split('/')[0];
const initialKind = initialHashKind==='tomica-news' ? 'tomica' : catalogKinds.includes(initialHashKind) ? initialHashKind : catalogKinds.includes(entryKind) ? entryKind : 'tomica';
const state = { kind:initialKind, items:[], cursor:null, loading:false, query:{}, sequence:0, detail:null, activeForm:0, page:1, pageSize:20, total:0, totalPages:1 };
let controller, searchTimer;
let routeSequence = 0, detailSequence = 0;
let newsIndexSequence = 0;
let imageScale = 1;
let detailReturnY = null;
let regions = [];
let restoringBrowse = false, autoArmed = true, autoBlocked = false, awaitScroll = false, autoScrollY = 0;
const tomicaListKey = 'dual-catalog:tomica-list:v1';
const listKeys = {tomica:tomicaListKey,pokemon:'dual-catalog:pokemon-list:v1'};

function readCatalogList(kind) {
  try {
    const saved=JSON.parse(sessionStorage.getItem(listKeys[kind]));
    if(!saved||!saved.query||typeof saved.query!=='object'||Array.isArray(saved.query))return null;
    const query={},keys=kind==='tomica'?['q','brand','year']:['q','type','region'];
    for(const key of keys)if(typeof saved.query[key]==='string'&&saved.query[key].length<=100)query[key]=saved.query[key];
    if(query.year&&!/^(unknown|[1-9][0-9]{0,3})$/.test(query.year))delete query.year;
    if(query.type&&!types.includes(query.type))delete query.type;
    if(query.region&&!['kanto','johto','hoenn','sinnoh','unova','kalos','alola','galar','hisui','paldea','unknown'].includes(query.region))delete query.region;
    return {query,page:Number.isInteger(saved.page)&&saved.page>0?saved.page:1,pageSize:[20,40,60,100].includes(saved.pageSize)?saved.pageSize:20,visibleCount:Number.isInteger(saved.visibleCount)&&saved.visibleCount>0?saved.visibleCount:12,scrollY:Number.isFinite(saved.scrollY)&&saved.scrollY>=0?saved.scrollY:0};
  } catch(_){return null;}
}
function rememberCatalogList(top=detailReturnY??window.scrollY) {
  try {sessionStorage.setItem(listKeys[state.kind],JSON.stringify({query:state.query,page:state.page,pageSize:state.pageSize,visibleCount:state.items.length,scrollY:top}));}catch(_){/* Browsing remains available without session storage. */}
}
function showDetailDialog() {
  if($('detail-dialog').open)return;
  if(detailReturnY===null)detailReturnY=window.scrollY;
  $('detail-dialog').dataset.returnCatalog=state.kind;
  rememberCatalogList();$('detail-dialog').showModal();
}
function hideDetailDialog() {
  const kind=state.kind,top=$('detail-dialog').dataset.returnCatalog===kind?(detailReturnY??window.scrollY):0;
  awaitScroll=true;autoArmed=false;autoScrollY=top;
  $('detail-dialog').close();detailReturnY=null;rememberCatalogList(top);
  window.scrollTo({top,behavior:'instant'});
  requestAnimationFrame(()=>{if(state.kind===kind&&!$('detail-dialog').open)window.scrollTo({top,behavior:'instant'});});
}
function closeDetail() {
  closeImageViewer();routeSequence++;detailSequence++;hideDetailDialog();history.replaceState(history.state,'','#'+state.kind);
}

function setImageScale(value) {
  imageScale=Math.max(1,Math.min(3,value));
  $('image-canvas').style.width=imageScale*100+'%';$('image-canvas').style.height=imageScale*100+'%';
  $('image-scale').textContent=Math.round(imageScale*100)+'%';
  $('image-zoom-out').disabled=imageScale===1;$('image-zoom-in').disabled=imageScale===3;
}
function closeImageViewer(){if($('image-viewer').open)$('image-viewer').close();}
function openImageViewer(img) {
  if(!img.naturalWidth)return;
  $('enlarged-image').src=img.src;$('enlarged-image').alt=img.alt;
  $('image-caption').textContent=img.alt;setImageScale(1);$('image-viewer').showModal();
  $('image-stage').scrollTo(0,0);
}
function bindDetailZoom(root) {
  root.querySelectorAll('.detail-visual img,.version-photo img,.news-photo img').forEach(img=>{
    img.classList.add('zoomable-image');img.tabIndex=0;img.setAttribute('role','button');img.setAttribute('aria-label','放大：'+img.alt);
    img.onclick=()=>openImageViewer(img);
    img.onkeydown=event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();openImageViewer(img);}};
  });
}

function imageURL(item) { return item.image_url || item.preview_image_url || null; }
function imageMarkup(item, url, name, lazy = false) {
  return `<span class="image-placeholder">${url ? '原图加载中…' : '暂无原图'}</span>` + (url ? `<img loading="${lazy ? 'lazy' : 'eager'}" fetchpriority="${lazy ? 'low' : 'auto'}" style="opacity:0" src="${escapeHTML(url)}" alt="${escapeHTML(name)}">` : '');
}
function bindImages(root) {
  root.querySelectorAll('img').forEach(img => {
    const parent = img.parentElement;
    const show = () => { if (!img.naturalWidth) return; const placeholder = parent.querySelector('.image-placeholder'); if (placeholder) placeholder.remove(); img.style.opacity = '1'; const label = parent.querySelector('.art-label, .detail-art-note'); if (label) label.textContent = '源站原图 · 来源见资料页'; };
    img.onload = show;
    img.onerror = () => { img.remove(); const placeholder = parent.querySelector('.image-placeholder'); if (placeholder) placeholder.textContent = '原图暂不可用'; const label = parent.querySelector('.art-label, .detail-art-note'); if (label) label.textContent = ''; };
    if (img.complete) { if (img.naturalWidth) show(); else img.onerror(); }
  });
}
function typeTags(values) { return (values || []).map(type=>`<span class="type-tag type-${escapeHTML(type)}">${escapeHTML(type)}</span>`).join(''); }
async function request(path, params = {}, signal) {
  const query = new URLSearchParams(Object.entries(params).filter(([,v])=>v!==null&&v!==undefined&&v!==''));
  const response = await fetch('/api/' + path + (query.size?'?'+query:''), {signal,priority:'high'});
  const value = await response.json();
  if (!response.ok) throw Object.assign(new Error(value.message || '连接暂时中断'), {status:response.status});
  return value;
}

function renderCards() {
  $('cards').innerHTML = state.items.map((item,index)=>{
    const name=item.name_display||item.name_original||item.name_zh;
    const subtitle=state.kind==='tomica'?(item.brand||'品牌待整理'):(item.name_en||'POKÉMON');
    const label=state.kind==='tomica'?'No. '+item.number:'#'+String(item.dex).padStart(4,'0');
    return `<button class="catalog-card" data-index="${index}" aria-label="查看${escapeHTML(name)}"><div class="card-art" data-type="${escapeHTML((item.types||[])[0]||'一般')}">${imageMarkup(item,imageURL(item),name,true)}<span class="art-label"></span></div><div class="card-number">${escapeHTML(label)}<span class="dot">·</span></div><h3 class="card-name">${escapeHTML(name)}</h3><div class="card-subtitle">${escapeHTML(subtitle)}</div><div class="card-foot"><div>${state.kind==='tomica'?`<span class="year-tag">${item.release_year?item.release_year+' 年':'年份待整理'}</span> <span>${escapeHTML(item.scale||'比例待整理')}</span>`:typeTags(item.types)}</div><span class="arrow">↗</span></div></button>`;
  }).join('');
  $('cards').querySelectorAll('.catalog-card').forEach(card=>card.onclick=()=>{const item=state.items[Number(card.dataset.index)];detailReturnY=window.scrollY;rememberCatalogList();location.hash=state.kind+'/'+(state.kind==='tomica'?item.id:item.dex);});
  bindImages($('cards'));
  const region=regions.find(r=>r.key===state.query.region);
  $('result-caption').textContent = state.kind==='tomica' ? `微缩车库 · 共 ${state.total} 款车型 · 第 ${state.page} / ${state.totalPages} 页` : `${region?(region.key==='unknown'?'未确认分类':region.name+'地区图鉴'):'全国图鉴'} · 已呈现 ${state.items.length} / ${state.total} 位宝可梦`;
  renderPagination();
}

function renderPagination() {
  const active = state.kind === 'tomica' && state.total > 0;
  $('pagination').hidden = !active;
  $('previous-page').disabled = state.loading || state.page <= 1;
  $('next-page').disabled = state.loading || state.page >= state.totalPages;
  $('page-jump-input').max = state.totalPages;
  $('page-jump-input').value = state.page;
  $('page-count').textContent = `共 ${state.totalPages} 页，每页 ${state.pageSize} 款`;
  $('page-size').value = String(state.pageSize);
  $('page-numbers').replaceChildren();
  if (!active) return;
  const pages = [...new Set([1, ...Array.from({length:5},(_,i)=>state.page+i-2), state.totalPages])].filter(n=>n>=1&&n<=state.totalPages).sort((a,b)=>a-b);
  let previous = 0;
  for (const n of pages) {
    if (previous && n-previous>1) { const gap=document.createElement('span');gap.textContent='…';$('page-numbers').append(gap); }
    const button=document.createElement('button');button.textContent=n;button.setAttribute('aria-label','第'+n+'页');button.disabled=state.loading;
    if(n===state.page){button.classList.add('selected');button.setAttribute('aria-current','page');}
    button.onclick=()=>changePage(n);$('page-numbers').append(button);previous=n;
  }
}
function changePage(page) {
  if(state.loading||page<1||page>state.totalPages||page===state.page)return;
  load(false,page).then(()=>{if(state.kind==='tomica')$('catalog').scrollIntoView({behavior:'smooth',block:'start'});});
}
async function load(reset=false, targetPage, pokemonLimit=12) {
  if (state.loading && !reset) return;
  const filterReset=reset&&state.kind==='pokemon'&&!restoringBrowse;
  const byPage=state.kind==='tomica',requestedPage=reset?1:targetPage||state.page;
  if(byPage)state.page=requestedPage;
  if(reset||byPage){state.sequence++;if(controller)controller.abort();state.items=[];state.cursor=null;}
  if(reset){
    autoBlocked=false;autoArmed=!filterReset;awaitScroll=filterReset;
    if(filterReset){$('catalog').scrollIntoView({behavior:'instant',block:'start'});autoScrollY=scrollY;}
  }
  const seq=state.sequence;state.loading=true;controller=new AbortController();$('feedback').textContent='正在翻阅图鉴…';
  if(reset||byPage){
    $('cards').querySelectorAll('img').forEach(img=>{img.onload=null;img.onerror=null;img.removeAttribute('src');});
    $('cards').innerHTML=Array(byPage?state.pageSize:6).fill('<div class="card-skeleton"></div>').join('');
  }
  renderPagination();
  try {
    const params=byPage?{...state.query,limit:state.pageSize,page:requestedPage}:{...state.query,limit:pokemonLimit,cursor:state.cursor};
    const response=await request(state.kind,params,controller.signal);
    if(seq!==state.sequence)return;
    if(byPage){state.items=response.items;state.total=response.total;state.page=response.page;state.totalPages=response.total_pages;}
    else {const combined=[...state.items,...response.items];state.items=[...new Map(combined.map(item=>[item.dex,item])).values()];state.total=response.total??state.items.length;}
    state.cursor=response.next_cursor;
    renderCards();rememberCatalogList();$('feedback').textContent=state.items.length?(byPage?'':state.cursor?'继续向下，发现更多宝可梦':'— 本次结果已全部呈现 —'):'暂时没有找到，换个条件再探索吧。';
  } catch(error) {
    if(error.name==='AbortError'||seq!==state.sequence)return;
    if(error.status===409&&!reset){state.loading=false;return load(true);}
    autoBlocked=true;if(reset||byPage)$('cards').replaceChildren();$('feedback').textContent=error.message+' ';const button=document.createElement('button');button.textContent='重新加载';button.onclick=()=>{autoBlocked=false;return load(state.items.length===0);};$('feedback').append(button);
  } finally {if(seq===state.sequence){state.loading=false;renderPagination();updateAutoBrowse();}}
}

function loadOnScroll() {
  if(state.kind!=='pokemon'||state.loading||!state.cursor||!state.items.length||restoringBrowse||autoBlocked||awaitScroll||!autoArmed||$('detail-dialog').open||$('image-viewer').open)return;
  if($('scroll-sentinel').getBoundingClientRect().top>innerHeight+180)return;
  autoArmed=false;autoScrollY=scrollY;load();
}
function updateAutoBrowse() {
  $('scroll-sentinel').hidden=state.kind!=='pokemon'||!state.cursor;
  if(!restoringBrowse&&!awaitScroll&&!autoBlocked&&state.kind==='pokemon'&&state.cursor&&document.documentElement.scrollHeight<=innerHeight+30){autoArmed=true;requestAnimationFrame(loadOnScroll);}
}
const browseObserver = new IntersectionObserver(entries=>{
  for(const entry of entries){
    if(!entry.isIntersecting){if(!restoringBrowse&&!awaitScroll)autoArmed=true;}
    else loadOnScroll();
  }
},{rootMargin:'180px 0px'});
window.addEventListener('scroll',()=>{
  const downward=scrollY>autoScrollY+2;autoScrollY=scrollY;
  if(restoringBrowse||$('detail-dialog').open||state.kind!=='pokemon')return;
  if(downward){awaitScroll=false;autoArmed=true;requestAnimationFrame(loadOnScroll);}
},{passive:true});
function renderRegions() {
  populate($('region'),regions.map(r=>[r.key,r.key==='unknown'?r.name:r.name+'地区']),'全部地区');$('region').value=state.query.region||'';
  const selected=regions.find(r=>r.key===state.query.region);
  $('region-note').textContent=selected?`全国编号 #${String(selected.national_range[0]).padStart(4,'0')}–#${String(selected.national_range[1]).padStart(4,'0')} · ${selected.species_count} 种`:'按 Wiki 全国编号分段归类，每种宝可梦只归属一个分类。';
  $('region-tabs').replaceChildren();
  for(const region of [{key:'',name:'全国'},...regions]){
    const button=document.createElement('button');button.textContent=region.name;button.className='region-tab';button.dataset.region=region.key;
    button.setAttribute('aria-pressed',String((state.query.region||'')===region.key));
    button.onclick=()=>{state.query.region=region.key;renderRegions();load(true);};$('region-tabs').append(button);
  }
}

async function restorePokemonList(saved) {
  const first=load(true,undefined,Math.min(100,saved.visibleCount)),sequence=state.sequence;
  await first;
  while(state.kind==='pokemon'&&state.sequence===sequence&&!state.loading&&state.cursor&&state.items.length<saved.visibleCount){
    const count=state.items.length;
    await load(false,undefined,Math.min(100,saved.visibleCount-count));
    if(state.items.length<=count)break;
  }
}

function populate(select,options,label){select.replaceChildren();for(const [value,text] of [['',label],...options]){const option=document.createElement('option');option.value=value;option.textContent=text;select.append(option);}}
function newsLink(month, product) { return '#tomica-news/'+month+(product?'/'+encodeURIComponent(product):''); }
async function loadNewsIndex() {
  const sequence=++newsIndexSequence;
  $('news-index').textContent='正在翻阅本月新发现…';
  try {
    const {items}=await request('tomica-news');
    if(sequence!==newsIndexSequence||state.kind!=='tomica')return;
    if(!items.length){$('news-index').textContent='新的发现，即将记录在这里。';return;}
    const latest=items[0], first=latest.products[0];
    $('news-index').innerHTML=`<nav class="news-months" aria-label="新品月份索引">${items.map(m=>`<a data-news-month="${escapeHTML(m.month)}" href="${newsLink(m.month)}" class="${m===latest?'selected':''}">${escapeHTML(m.month.replace('-','年')+'月新品情报')}</a>`).join('')}</nav><a class="news-feature" href="${newsLink(latest.month,first.id)}"><div class="news-cover">${imageMarkup(first,first.image_url,first.name)}</div><span class="news-issue">${escapeHTML(latest.title)} · ${latest.product_count} 组新品图文</span><h3>${escapeHTML(first.name)}</h3><p>${escapeHTML(first.name_zh||'多角度原图与细节记录')}</p></a><div class="news-more-products">${latest.products.slice(1).map(p=>`<a href="${newsLink(latest.month,p.id)}">${escapeHTML(p.name)}<span>↗</span></a>`).join('')}</div><a class="news-open-month" href="${newsLink(latest.month)}">翻开本期月刊 <span>↗</span></a>`;
    bindImages($('news-index'));
  } catch(error) {
    if(sequence!==newsIndexSequence||state.kind!=='tomica')return;
    $('news-index').textContent='新品月刊暂时无法加载。';
    const button=document.createElement('button');button.textContent='重新加载';button.onclick=loadNewsIndex;$('news-index').append(button);
  }
}
async function openNews(month, productId) {
  const sequence=++detailSequence;
  $('detail-dialog').classList.remove('pokemon-detail-dialog');$('detail-dialog').classList.add('news-detail-dialog');
  $('detail-root').innerHTML='<div class="detail-content">正在翻开新品月刊…</div>';
  showDetailDialog();
  try {
    const issue=await request('tomica-news/'+encodeURIComponent(month));
    if(sequence!==detailSequence||state.kind!=='tomica')return;
    const entries=issue.articles.flatMap(article=>article.products.map(product=>({article,product})));
    const selected=productId?entries.find(e=>e.product.id===productId):entries[0];
    if(!selected)throw new Error('本月暂未收录这款新品');
    const {article,product}=selected;
    $('detail-root').innerHTML=`<article class="news-article"><header class="news-article-heading"><span class="news-kicker">NEW ARRIVALS / 新品月刊</span><h2>${escapeHTML(issue.title)}<span>本月的新发现</span></h2><p>${escapeHTML(article.title)}</p></header><nav class="news-product-tabs" aria-label="本月新品">${entries.map(e=>`<a data-news-product="${escapeHTML(e.product.id)}" class="${e.product.id===product.id?'selected':''}" href="${newsLink(month,e.product.id)}" ${e.product.id===product.id?'aria-current="page"':''}>${escapeHTML(e.product.name)}</a>`).join('')}</nav><section class="news-product"><div class="news-product-heading"><span class="news-kicker">${escapeHTML(product.name_zh||'NEW RELEASE')}</span><h3>${escapeHTML(product.name)}</h3><p>${escapeHTML(product.summary)}</p></div><div class="news-observations"><h4>图中细节</h4><ul>${product.observations.map(text=>`<li>${escapeHTML(text)}</li>`).join('')}</ul></div><div class="news-gallery">${product.photos.map((photo,i)=>`<figure class="news-photo ${i===0?'news-lead-photo':''}" data-news-digest="${photo.digest}">${imageMarkup(photo,photo.image_url,product.name+' · '+photo.caption,i>0)}<figcaption><span>${String(i+1).padStart(2,'0')}</span>${escapeHTML(photo.caption)}<small>查看原图 ↗</small></figcaption></figure>`).join('')}</div></section><footer class="news-source"><span>${escapeHTML(article.source_name)} · 用户提供原图</span><a href="${escapeHTML(article.source_url)}" target="_blank" rel="noopener noreferrer">查看原文 ↗</a><p>原图保留水印；“图中细节”为依据图片整理的观察。</p></footer></article>`;
    bindImages($('detail-root'));bindDetailZoom($('detail-root'));
    $('detail-dialog').scrollTop=0;
    document.querySelectorAll('[data-news-month]').forEach(a=>a.classList.toggle('selected',a.dataset.newsMonth===month));
  } catch(error) {
    if(sequence!==detailSequence||state.kind!=='tomica')return;
    $('detail-root').replaceChildren();const box=document.createElement('div');box.className='detail-content';box.textContent=error.message;$('detail-root').append(box);
  }
}
async function selectKind(kind, restored=null) {
  clearTimeout(searchTimer);
  restoringBrowse=true;awaitScroll=Boolean(restored);autoArmed=!restored;autoBlocked=false;
  state.kind=kind;state.query=restored?{...restored.query}:{};state.page=restored&&kind==='tomica'?restored.page:1;if(restored&&kind==='tomica')state.pageSize=restored.pageSize;state.total=0;state.totalPages=1;$('search').value=state.query.q||'';$('brand').value='';$('year').value='';$('type').value=state.query.type||'';
  document.body.dataset.catalog = kind;
  newsIndexSequence++;$('news-sidebar').hidden=kind!=='tomica';
  const newsPromise=kind==='tomica'?loadNewsIndex():null;
  if(kind==='tomica'){$('cards').classList.remove('list-mode');$('grid-view').classList.add('selected');$('list-view').classList.remove('selected');}
  document.querySelector('.brand').href = '#' + kind;
  document.body.classList.toggle('pokemon-theme',kind==='pokemon');document.querySelectorAll('[data-kind]').forEach(button=>button.classList.toggle('active',button.dataset.kind===kind));
  $('breadcrumb').textContent=kind==='tomica'?'多美卡':'宝可梦';$('heading').innerHTML=kind==='tomica'?'把热爱，<span>一件件收好。</span>':'每一次相遇，<span>都有迹可循。</span>';
  $('description').textContent=kind==='tomica'?'从一辆小车开始，发现微缩世界里的无限可能。':'从 #0001 出发，记录宝可梦世界里的每一份惊喜。';
  $('feature-label').textContent=kind==='tomica'?'TOMICA / 微缩收藏档案':'POKÉDEX / 宝可梦探索手册';$('feature-title').innerHTML=kind==='tomica'?'属于你的<br>车库小时光。':'下一次相遇，<br>就从这里开始。';$('feature-subtitle').textContent=kind==='tomica'?'穿过年份，找到那一辆心动的小车。':'循着图鉴编号，认识每一位特别的伙伴。';
  $('feature-art').replaceChildren();$('catalog-title').innerHTML=(kind==='tomica'?'探索多美卡':'探索宝可梦')+'<span class="title-mark">✦</span>';$('catalog-description').textContent=kind==='tomica'?'沿着年份与品牌，寻找你的下一份喜欢。':'每一个编号背后，都藏着一个独特的故事。';
  $('search').placeholder=kind==='tomica'?'搜索车型、品牌或编号':'搜索名称或全国编号';$('sort-note').textContent=kind==='tomica'?'年份顺序 ↑':'全国编号 ↑';$('brand-wrap').classList.toggle('hidden',kind!=='tomica');$('year-wrap').classList.toggle('hidden',kind!=='tomica');$('type-wrap').classList.toggle('hidden',kind!=='pokemon');
  $('brand-wrap').hidden = kind !== 'tomica';
  $('year-wrap').hidden = kind !== 'tomica';
  $('type-wrap').hidden = kind !== 'pokemon';
  $('region-panel').hidden=kind!=='pokemon';$('region-wrap').hidden=kind!=='pokemon';
  document.body.classList.remove('catalog-loading');
  const promise=restored?(kind==='pokemon'?restorePokemonList(restored):load(false,restored.page)):load(true);
  const selectionSequence=state.sequence;
  if(kind==='pokemon'){
    try{const metadata=await request('pokemon/regions');if(state.kind===kind){regions=metadata.items;renderRegions();}}catch(_){if(state.kind===kind)$('region-note').textContent='地区索引暂时无法加载，请刷新重试。';}
  }
  if(kind==='tomica'){try{const filters=await request('tomica/filters');if(state.kind===kind){populate($('brand'),[...filters.brands.map(v=>[v,v]),...(filters.unknown_brand?[['unknown','未知品牌']]:[])],'全部品牌');populate($('year'),[...filters.years.map(v=>[String(v),v+' 年']),...(filters.unknown_year?[['unknown','未知年份']]:[])],'全部年份');$('brand').value=state.query.brand||'';$('year').value=state.query.year||'';}}catch(_){}}
  await promise;
  if(restored&&newsPromise)await newsPromise;
  if(state.kind!==kind||(restored&&state.sequence!==selectionSequence))return false;
  try {
    const featured = kind === 'pokemon' ? await request('pokemon/25') : state.items[0];
    if (state.kind === kind && featured) {
      $('feature-art').innerHTML = imageMarkup(featured, imageURL(featured), featured.name_zh || featured.name_original);
      bindImages($('feature-art'));
    }
  } catch (_) { /* Catalog remains usable when the featured item is unavailable. */ }
  if(!restored&&state.kind===kind){restoringBrowse=false;updateAutoBrowse();}
  return !restored||state.sequence===selectionSequence;
}

function fact(label,value){return `<div><div class="fact-label">${escapeHTML(label)}</div><div class="fact-value">${escapeHTML(value ?? '暂无资料')}</div></div>`;}
function renderDetail() {
  const item=state.detail,kind=state.kind,form=(item.forms||[])[state.activeForm];
  const selectedImage = state.activeForm > 0 ? (form && imageURL(form)) : imageURL(item);
  const title=item.name_display||item.name_original||item.name_zh;
  const label=kind==='tomica'?'No. '+item.number:'#'+String(item.dex).padStart(4,'0');
  let sections;
  if(kind==='tomica'){
    sections=`<div class="detail-section"><h3>基础档案 / THE DETAILS</h3><div class="facts">${fact('汽车品牌',item.brand)}${fact('基础车型发售年份',item.release_year)}${fact('比例',item.scale)}${fact('系列',item.series)}</div></div><div class="detail-section"><h3>版本记录 · ${(item.variants||[]).length}</h3>${(item.variants||[]).map(v=>`<div class="version"><div class="version-photo">${imageMarkup(v,imageURL(v),v.variant_code||title,true)}</div>${escapeHTML(v.variant_code||'版本编号待整理')}<small>${escapeHTML(v.description||'暂无说明')}<br>${escapeHTML(v.country||'产地未知')} · ${escapeHTML(v.release_year?v.release_year+' 年':'版本发售年份未知')}</small></div>`).join('')||'<div class="source-note">暂无版本资料</div>'}</div>`;
  }else{
    sections=`<div class="detail-section"><h3>基础档案 / THE DETAILS</h3><div class="facts">${fact('身高',item.height_m!=null?item.height_m+' m':null)}${fact('体重',item.weight_kg!=null?item.weight_kg+' kg':null)}${fact('日文名',item.name_ja)}${fact('特性',(item.abilities||[]).join(' / ')||null)}</div></div><div class="detail-section"><h3>形态与属性</h3><div>${(item.forms||[]).map((f,index)=>`<button class="form-button ${index===state.activeForm?'active':''}" data-form="${index}">${escapeHTML(f.display_name)}</button>`).join('')}</div><div>${typeTags(form?form.types:item.types)}</div></div><div class="detail-section"><h3>进化关系</h3>${(item.evolutions||[]).map(e=>`<div class="evolution-row"><button data-evolution="${e.from_dex}" ${e.from_available?'':'disabled'}>${escapeHTML(e.from_name||'#'+e.from_dex)}</button><span>→</span><button data-evolution="${e.to_dex}" ${e.to_available?'':'disabled'}>${escapeHTML(e.to_name||'#'+e.to_dex)}</button><small>${escapeHTML(e.condition||'条件待整理')}</small></div>`).join('')||'<div class="source-note">暂无进化资料</div>'}</div>`;
  }
  $('detail-dialog').classList.remove('news-detail-dialog');
  $('detail-dialog').classList.toggle('pokemon-detail-dialog',kind==='pokemon');
  const sourceLink=kind==='pokemon'?`${/^https?:\/\//.test(item.source_url)?`<a href="${escapeHTML(item.source_url)}" target="_blank" rel="noopener noreferrer">查看资料来源 ↗</a>`:'演示记录 · 用于浏览与样式调整'}<br>`:'';
  $('detail-root').innerHTML=`<div class="detail-layout"><div class="detail-visual">${imageMarkup(item,selectedImage,title)}<div class="detail-art-note"></div></div><div class="detail-content"><div class="detail-eyebrow">${escapeHTML(label)} / LITTLE ATLAS</div><h2>${escapeHTML(title)}</h2><div class="detail-subtitle">${escapeHTML(item.name_en||item.name_original)}</div>${kind==='pokemon'?`<div class="detail-tags">${typeTags(form?form.types:item.types)}</div>`:''}${sections}<div class="source-note">${sourceLink}最近更新：${escapeHTML(item.updated_at?new Date(item.updated_at).toLocaleDateString('zh-CN'):'待更新')}</div></div></div>`;
  if(kind==='pokemon'){
    const extra=document.createElement('section');extra.id='pokemon-extra';extra.className='pokemon-extra';$('detail-root').append(extra);
    window.PokemonDetails.mount(extra,item.extra,{escapeHTML,typeTags,imageMarkup,imageURL,bindImages});
  }
  bindImages($('detail-root'));
  if(kind==='tomica')bindDetailZoom($('detail-root'));
  $('detail-root').querySelectorAll('[data-form]').forEach(button=>button.onclick=()=>{state.activeForm=Number(button.dataset.form);renderDetail();});
  $('detail-root').querySelectorAll('[data-evolution]').forEach(button=>button.onclick=()=>location.hash='pokemon/'+button.dataset.evolution);
}
async function openDetail(id, kind=state.kind){
  const sequence = ++detailSequence;
  $('detail-dialog').classList.remove('news-detail-dialog');
  state.activeForm=0;$('detail-root').innerHTML='<div class="detail-content">正在打开图鉴…</div>';showDetailDialog();
  try {
    const detail=await request(kind+'/'+encodeURIComponent(id));
    if(sequence!==detailSequence||state.kind!==kind)return;
    state.detail=detail;renderDetail();
  }catch(error){if(sequence===detailSequence&&state.kind===kind)$('detail-root').textContent=error.message;}
}
async function route(){
  closeImageViewer();
  const [kind,id,productId]=location.hash.slice(1).split('/');
  if(kind==='catalog'){$('catalog').scrollIntoView({behavior:'smooth'});return;}
  const next=kind==='tomica-news'?'tomica':catalogKinds.includes(kind)?kind:catalogKinds.includes(entryKind)?entryKind:state.kind;
  const sequence=++routeSequence;
  const changed=state.kind!==next;
  if(changed){if($('detail-dialog').open)hideDetailDialog();rememberCatalogList();}
  const restored=state.sequence===0||changed?readCatalogList(next):null;
  if(changed&&!restored)window.scrollTo({top:0,behavior:'instant'});
  let restoredApplied=true;
  if(state.kind!==next||state.sequence===0)restoredApplied=await selectKind(next,restored);
  if(sequence!==routeSequence||state.kind!==next)return;
  if(restored&&restoredApplied!==false){window.scrollTo({top:restored.scrollY,behavior:'instant'});detailReturnY=id?restored.scrollY:null;rememberCatalogList(restored.scrollY);}
  if(kind==='tomica-news'&&id)await openNews(id,productId);
  else if(id)await openDetail(id,next);
  else {detailSequence++;if($('detail-dialog').open)hideDetailDialog();}
  if(sequence===routeSequence){await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));restoringBrowse=false;autoScrollY=scrollY;if(restored){awaitScroll=true;autoArmed=false;}updateAutoBrowse();}
}
document.querySelectorAll('[data-kind]').forEach(button=>button.onclick=()=>{if(state.kind===button.dataset.kind&&!$('detail-dialog').open)return;location.hash=button.dataset.kind;});
$('search').oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>{state.query.q=$('search').value.trim();load(true);},280);};
for(const field of ['brand','year','type'])$(field).onchange=()=>{state.query[field]=$(field).value;load(true);};
$('region').onchange=()=>{state.query.region=$('region').value;renderRegions();load(true);};
$('previous-page').onclick=()=>changePage(state.page-1);$('next-page').onclick=()=>changePage(state.page+1);$('page-jump').onsubmit=event=>{event.preventDefault();changePage(Math.trunc(Number($('page-jump-input').value)));};
$('page-size').onchange=()=>{const size=Number($('page-size').value);if(state.kind!=='tomica'||![20,40,60,100].includes(size))return;state.pageSize=size;load(true);};
$('reset').onclick=()=>selectKind(state.kind);
$('grid-view').onclick=()=>{$('cards').classList.remove('list-mode');$('grid-view').classList.add('selected');$('list-view').classList.remove('selected');};
$('list-view').onclick=()=>{$('cards').classList.add('list-mode');$('list-view').classList.add('selected');$('grid-view').classList.remove('selected');};
$('explore-link').onclick=event=>{event.preventDefault();$('catalog').scrollIntoView({behavior:'smooth'});};
$('close-detail').onclick=closeDetail;$('detail-dialog').onclick=event=>{if(event.target===$('detail-dialog'))closeDetail();};$('detail-dialog').addEventListener('cancel',event=>{event.preventDefault();closeDetail();});
$('close-image').onclick=closeImageViewer;$('image-viewer').onclick=event=>{if(event.target===$('image-viewer'))closeImageViewer();};
$('image-zoom-in').onclick=()=>setImageScale(imageScale+.5);$('image-zoom-out').onclick=()=>setImageScale(imageScale-.5);$('image-reset').onclick=()=>{setImageScale(1);$('image-stage').scrollTo(0,0);};
populate($('type'),types.map(v=>[v,v]),'全部属性');window.addEventListener('hashchange',route);
window.addEventListener('pagehide',()=>rememberCatalogList());
fetch('/health/ready').then(r=>{$('connection').textContent=r.ok?'图鉴服务已连接':'图鉴正在准备';}).catch(()=>$('connection').textContent='暂时离线');
browseObserver.observe($('scroll-sentinel'));route();
