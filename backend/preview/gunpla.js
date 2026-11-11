'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const key = 'dual-catalog:gunpla-list:v1';
  const defaults = {mode:'grade',grade:'',series:'',sale_type:'1',scale:'',q:'',page:1,limit:20};
  const state = {query:{...defaults},items:[],total:0,total_pages:1,loading:true,detail:null,ready:false};
  let metadata, home, controller, detailController, sequence=0, detailSequence=0, returnY=0, searchTimer, channel='', imageScale=1;
  history.scrollRestoration='manual';
  function saved(){try{const value=JSON.parse(sessionStorage.getItem(key));if(!value||!value.query)return null;const q={...defaults};for(const field of Object.keys(defaults))if(typeof value.query[field]===typeof defaults[field])q[field]=value.query[field];if(!['grade','series'].includes(q.mode))return null;if(![20,40,60,100].includes(q.limit)||q.page<1)return null;return {query:q,scrollY:Number.isFinite(value.scrollY)?Math.max(0,value.scrollY):0};}catch(_){return null;}}
  function remember(top=$('detail-dialog').open?returnY:scrollY){try{sessionStorage.setItem(key,JSON.stringify({query:state.query,scrollY:top}));}catch(_){}}
  function picture(url,name,lazy=true){return url?`<img src="${escape(url)}" alt="${escape(name)}" loading="${lazy?'lazy':'eager'}" decoding="async">`:'<span class="missing">暂无原图</span>';}
  function imageErrors(root){root.querySelectorAll('img').forEach(img=>img.onerror=()=>{const note=document.createElement('span');note.className='missing';note.textContent='原图暂不可用';img.replaceWith(note);});}
  async function request(path='',params={},signal){
    const query=new URLSearchParams(Object.entries(params).filter(([,v])=>v!==''&&v!==null&&v!==undefined));
    const response=await fetch('/api/gunpla'+path+(query.size?'?'+query:''),{credentials:'same-origin',cache:'no-store',signal});
    const body=await response.json();
    if(!response.ok){if(response.status===401||body.code==='PASSWORD_CHANGE_REQUIRED')window.CatalogAuth?.expire(body.code);throw new Error(body.message||'模型图鉴暂时无法加载，请重试');}
    return body;
  }
  const workName = id => metadata.series_groups.flatMap(g=>g.items).find(r=>r.id===id)?.name||'全部高达作品';
  function selection(){
    const series=state.query.mode==='series';$('grade-panel').hidden=series;$('series-panel').hidden=!series;
    document.querySelectorAll('[data-mode]').forEach(b=>{const active=b.dataset.mode===state.query.mode;b.classList.toggle('selected',active);b.setAttribute('aria-selected',String(active));});
    document.querySelectorAll('[data-grade]').forEach(b=>b.classList.toggle('selected',b.dataset.grade===state.query.grade));
    document.querySelectorAll('[data-sale]').forEach(b=>{const active=b.dataset.sale===state.query.sale_type;b.classList.toggle('selected',active);b.setAttribute('aria-selected',String(active));});
    $('selected-series').textContent=workName(state.query.series);$('gunpla-search').value=state.query.q;$('gunpla-scale').value=state.query.scale;$('gunpla-page-size').value=String(state.query.limit);
  }
  function renderFilters(){
    $('grade-options').innerHTML='<button class="grade-option" data-grade=""><b>ALL</b><span>全部规格</span></button>'+metadata.brands.map(r=>`<button class="grade-option" data-grade="${escape(r.id)}" title="${escape(r.name)}">${r.preview_image_url?picture(r.preview_image_url,r.name):''}<span>${escape(r.name)}</span></button>`).join('');
    $('grade-options').querySelectorAll('[data-grade]').forEach(b=>b.onclick=()=>setFilters({grade:b.dataset.grade}));
    $('sale-types').innerHTML=metadata.sale_types.map(r=>`<button class="sale-type" data-sale="${escape(r.id)}" role="tab">${escape(r.name)}</button>`).join('');
    $('sale-types').querySelectorAll('[data-sale]').forEach(b=>b.onclick=()=>setFilters({sale_type:b.dataset.sale}));
    $('gunpla-scale').innerHTML='<option value="">全部比例</option>'+metadata.scales.map(s=>`<option value="${escape(s)}">${escape(s)}</option>`).join('')+'<option value="unscaled">非比例 / 未标注</option>';
    $('series-groups').innerHTML=metadata.series_groups.map(g=>`<section class="series-decade" data-decade="${escape(g.id)}"><h3>${escape(g.name)}</h3><div class="series-works">${g.items.map(r=>`<button class="series-work" data-series="${escape(r.id)}">${r.preview_image_url?picture(r.preview_image_url,r.name):''}<span>${escape(r.name)}</span></button>`).join('')}</div></section>`).join('');
    $('series-groups').querySelectorAll('[data-series]').forEach(b=>b.onclick=()=>{setFilters({series:b.dataset.series});$('series-dialog').close();});
    imageErrors($('grade-options'));imageErrors($('series-groups'));selection();
  }
  function renderCards(){
    const sales=Object.fromEntries(metadata.sale_types.map(r=>[r.id,r.name]));
    $('gunpla-cards').innerHTML=state.items.map(r=>`<button class="gunpla-card" data-product="${escape(r.id)}" aria-label="查看 ${escape(r.name)}"><div class="gunpla-card-image">${picture(r.preview_image_url,r.name)}</div><div class="gunpla-card-copy"><span class="model-scale">${escape(r.scale||'GUNPLA')}</span><h3>${escape(r.name)}</h3><span class="model-date">${escape(r.release_text||'发售时间未公布')}</span><div class="model-badges">${r.sale_types.map(s=>`<span class="sale-${s}">${escape(sales[s])}</span>`).join('')}</div></div></button>`).join('');
    $('gunpla-cards').querySelectorAll('[data-product]').forEach(b=>b.onclick=()=>openProduct(b.dataset.product));
    imageErrors($('gunpla-cards'));
    $('gunpla-result').textContent=state.total.toLocaleString()+' 款模型 · 发售时间由新到旧';
    $('gunpla-prev').disabled=state.query.page<=1||state.loading;$('gunpla-next').disabled=state.query.page>=state.total_pages||state.loading;
    const pages=[...new Set([1,state.query.page-1,state.query.page,state.query.page+1,state.total_pages])].filter(n=>n>=1&&n<=state.total_pages).sort((a,b)=>a-b);
    $('gunpla-page-numbers').innerHTML=pages.map(n=>`<button class="${n===state.query.page?'selected':''}" data-page="${n}" aria-label="第${n}页">${n}</button>`).join('');
    $('gunpla-page-numbers').querySelectorAll('[data-page]').forEach(b=>b.onclick=()=>changePage(Number(b.dataset.page)));
    $('gunpla-page-count').textContent=`${state.query.page} / ${state.total_pages} 页`;
  }
  async function load(){
    const current=++sequence;controller?.abort();controller=new AbortController();state.loading=true;
    $('gunpla-cards').setAttribute('aria-busy','true');$('gunpla-feedback').textContent='正在翻阅模型档案…';
    try{
      const result=await request('',state.query,controller.signal);if(current!==sequence)return;
      state.items=result.items;state.total=result.total;state.total_pages=result.total_pages;state.query.page=result.page;state.loading=false;
      renderCards();$('gunpla-feedback').textContent=state.total?'':'暂时没有符合条件的模型，试试其他规格或作品。';remember();
    }catch(error){if(current===sequence&&error.name!=='AbortError'){$('gunpla-feedback').textContent=error.message;const b=document.createElement('button');b.textContent='重试';b.onclick=load;$('gunpla-feedback').append(' ',b);}}
    finally{if(current===sequence){state.loading=false;$('gunpla-cards').setAttribute('aria-busy','false');}}
  }
  function setFilters(patch){
    const next={...state.query,...patch,page:1};
    if(patch.mode&&patch.mode!==state.query.mode){next.grade='';next.series='';next.sale_type=patch.mode==='series'?'':'1';next.scale='';}
    if(next.mode==='series'){next.grade='';next.sale_type='';}else next.series='';
    state.query=next;selection();remember();return load();
  }
  async function changePage(page){if(state.loading||page<1||page>state.total_pages)return;state.query.page=page;await load();$('gunpla-catalog').scrollIntoView({behavior:'instant',block:'start'});remember();}
  function renderEvents(){
    const items=home.events.filter(r=>!channel||r.channel===channel);
    $('gunpla-events').innerHTML=items.map(r=>`<button class="event-card" data-event="${escape(r.id)}">${picture(r.preview_image_url,r.name)}<div class="event-badges"><span>${escape(r.channel||'活动')}</span>${r.status_text?`<span class="ended">${escape(r.status_text)}</span>`:''}</div><b>${escape(r.name)}</b><small>${escape(r.date_text||'')}</small></button>`).join('')||'<p class="gunpla-rail-caption">暂无活动资料</p>';
    $('gunpla-events').querySelectorAll('[data-event]').forEach(b=>b.onclick=()=>{const event=home.events.find(r=>r.id===b.dataset.event);$('event-content').innerHTML=`<span class="gunpla-kicker">EVENT & CAMPAIGN</span><h2>${escape(event.name)}</h2><p>${escape([event.channel,event.status_text,event.date_text].filter(Boolean).join(' · '))}</p>${picture(event.preview_image_url,event.name,false)}`;zoomable($('event-content'));$('event-dialog').showModal();});
    imageErrors($('gunpla-events'));
  }
  function renderHome(){
    renderEvents();$('gunpla-upcoming').innerHTML=home.upcoming.map(g=>`<section class="release-month"><h3>${escape(g.month.replace('-','年'))}月 <small>· ${g.total}款</small></h3>${g.items.slice(0,6).map(r=>`<button class="release-item" data-upcoming="${escape(r.id)}">${picture(r.preview_image_url,r.name)}<span><b>${escape(r.name)}</b><small>${escape(r.release_text||'')}</small></span></button>`).join('')}</section>`).join('')||'<p class="gunpla-rail-caption">暂无已公布的后续发售计划</p>';
    $('gunpla-upcoming').querySelectorAll('[data-upcoming]').forEach(b=>b.onclick=()=>openProduct(b.dataset.upcoming));
    $('gunpla-announcements').innerHTML=home.announcements.slice(0,4).map(r=>`<p>${escape(r.name)}<small>${escape(r.date_text||'')}</small></p>`).join('');imageErrors($('gunpla-upcoming'));
  }
  function openProduct(id){returnY=scrollY;remember(returnY);if(location.hash==='#product/'+id)route();else location.hash='product/'+id;}
  async function showProduct(id){
    const current=++detailSequence;detailController?.abort();detailController=new AbortController();
    if(!$('detail-dialog').open){returnY=scrollY;$('detail-dialog').showModal();}
    $('detail-root').innerHTML='<div class="gunpla-detail">正在展开模型详情…</div>';
    try{
      const item=await request('/products/'+encodeURIComponent(id),{},detailController.signal);if(current!==detailSequence)return;
      state.detail=item;const photos=[...new Set([...item.gallery,...item.detail_images])];
      $('detail-root').innerHTML=`<article class="gunpla-detail"><span class="gunpla-kicker">GUNPLA MODEL ARCHIVE</span><h2>${escape(item.name)}</h2><div class="gunpla-gallery-hero">${picture(item.gallery[0]||item.cover,item.name,false)}</div><nav class="gunpla-thumbnails" aria-label="模型全部商品图">${item.gallery.map((url,i)=>`<button data-photo="${i}" class="${i===0?'selected':''}" aria-label="商品图 ${i+1}">${picture(url,item.name+' · '+(i+1),false)}</button>`).join('')}</nav><div class="gunpla-facts"><div><span>官方价格 · 人民币</span><b>${escape(item.price_cny_text||'未公布')}</b></div><div><span>日本建议零售价</span><b>${escape(item.price_jpy_text||'未公布')}</b></div><div><span>发售日期</span><b>${escape(item.release_text||'未公布')}</b></div></div><section class="gunpla-detail-photos"><h3>商品图与细节 · ${photos.length} 张</h3><div class="photo-grid">${photos.map((url,i)=>picture(url,item.name+' · 细节 '+(i+1))).join('')}</div></section></article>`;
      const hero=$('detail-root').querySelector('.gunpla-gallery-hero img');
      $('detail-root').querySelectorAll('[data-photo]').forEach(b=>b.onclick=()=>{hero.src=item.gallery[Number(b.dataset.photo)];$('detail-root').querySelectorAll('[data-photo]').forEach(other=>other.classList.toggle('selected',other===b));});
      zoomable($('detail-root'));imageErrors($('detail-root'));$('detail-root').scrollTop=0;
    }catch(error){if(current===detailSequence&&error.name!=='AbortError')$('detail-root').innerHTML=`<div class="gunpla-detail">${escape(error.message)}</div>`;}
  }
  function closeDetail(updateURL=true){
    closeViewer();detailSequence++;detailController?.abort();state.detail=null;if($('detail-dialog').open)$('detail-dialog').close();
    if(updateURL)history.replaceState(history.state,'',location.pathname+location.search);
    scrollTo({top:returnY,behavior:'instant'});requestAnimationFrame(()=>{if(!$('detail-dialog').open)scrollTo({top:returnY,behavior:'instant'});});remember(returnY);
  }
  function route(){const match=location.hash.match(/^#product\/([1-9][0-9]*)$/);if(match)return showProduct(match[1]);if($('detail-dialog').open)closeDetail(false);}
  function setImageScale(value){imageScale=Math.max(1,Math.min(3,value));$('image-canvas').style.width=imageScale*100+'%';$('image-canvas').style.height=imageScale*100+'%';$('image-scale').textContent=Math.round(imageScale*100)+'%';$('image-zoom-out').disabled=imageScale===1;$('image-zoom-in').disabled=imageScale===3;}
  function closeViewer(){if($('image-viewer').open)$('image-viewer').close();}
  function openViewer(img){if(!img.naturalWidth)return;$('enlarged-image').src=img.src;$('enlarged-image').alt=img.alt;$('image-caption').textContent=img.alt;setImageScale(1);$('image-viewer').showModal();$('image-stage').scrollTo(0,0);}
  function zoomable(root){root.querySelectorAll('.gunpla-gallery-hero img,.photo-grid img,#event-content img').forEach(img=>{img.tabIndex=0;img.setAttribute('role','button');img.setAttribute('aria-label','放大 '+img.alt);img.onclick=()=>openViewer(img);img.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();openViewer(img);}};});}
  document.querySelectorAll('[data-mode]').forEach(b=>b.onclick=()=>setFilters({mode:b.dataset.mode}));
  document.querySelectorAll('[data-channel]').forEach(b=>b.onclick=()=>{channel=b.dataset.channel;document.querySelectorAll('[data-channel]').forEach(other=>other.classList.toggle('selected',other===b));renderEvents();});
  $('gunpla-search').oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>setFilters({q:$('gunpla-search').value.trim()}),280);};
  $('gunpla-scale').onchange=()=>setFilters({scale:$('gunpla-scale').value});$('gunpla-page-size').onchange=()=>setFilters({limit:Number($('gunpla-page-size').value)});
  $('gunpla-reset').onclick=()=>{state.query={...defaults};selection();remember(0);load();};$('gunpla-prev').onclick=()=>changePage(state.query.page-1);$('gunpla-next').onclick=()=>changePage(state.query.page+1);
  $('open-series').onclick=()=>$('series-dialog').showModal();$('close-series').onclick=()=>$('series-dialog').close();$('all-series').onclick=()=>{setFilters({series:''});$('series-dialog').close();};
  $('close-detail').onclick=()=>closeDetail();$('detail-dialog').onclick=e=>{if(e.target===$('detail-dialog'))closeDetail();};$('detail-dialog').oncancel=e=>{e.preventDefault();closeDetail();};$('close-event').onclick=()=>$('event-dialog').close();
  $('close-image').onclick=closeViewer;$('image-zoom-in').onclick=()=>setImageScale(imageScale+.5);$('image-zoom-out').onclick=()=>setImageScale(imageScale-.5);$('image-reset').onclick=()=>{setImageScale(1);$('image-stage').scrollTo(0,0);};
  addEventListener('hashchange',route);addEventListener('pagehide',()=>remember());addEventListener('resize',()=>{if($('image-viewer').open)setImageScale(imageScale);});
  window.GunplaPage={state,load,setFilters,closeDetail,openProduct};
  (async()=>{
    try{
      await window.CatalogAuth?.ready;if(window.CatalogAuth?.expired)return;
      const snapshot=saved();if(snapshot)state.query=snapshot.query;
      [metadata,home]=await Promise.all([request('/filters'),request('/home')]);renderFilters();renderHome();await load();
      await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
      returnY=snapshot?.scrollY||0;scrollTo({top:returnY,behavior:'instant'});remember(returnY);await route();state.ready=true;
      $('connection').textContent='图鉴服务已连接';
    }catch(error){$('gunpla-feedback').textContent=error.message;$('connection').textContent='暂时无法连接';}
  })();
})();
