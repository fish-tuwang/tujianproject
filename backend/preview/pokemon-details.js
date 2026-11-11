'use strict';
window.PokemonDetails = {
  mount(root, extra = {}, ui) {
    const e = ui.escapeHTML;
    const tabs = [['stats','种族值'],['acquisition','获得方式'],['matchups','属性相性'],['learn','学会的招式'],['machine','招式学习器'],['shiny','异色对比']];
    let active = 'stats', selected = 0, query = '', game = '';
    const empty = '<div class="extra-empty">源站暂无这项资料</div>';
    const options = (values, current) => values.map((value,index)=>`<option value="${index}" ${index===current?'selected':''}>${e(value)}</option>`).join('');
    const select = values => `<label class="extra-select">查看资料<select id="extra-select">${options(values,selected)}</select></label>`;
    const search = placeholder => `<input class="extra-search" id="extra-search" type="search" value="${e(query)}" placeholder="${e(placeholder)}" aria-label="${e(placeholder)}">`;
    const match = value => String(value).toLowerCase().includes(query.toLowerCase());
    function content() {
      if (active === 'stats') {
        const groups = extra.base_stats || [], group = groups[selected];
        if (!group) return empty;
        return select(groups.map(g=>g.label)) + `<div class="stat-total">种族值合计 <strong>${group.total}</strong></div><div class="stat-chart">${group.stats.map((stat,index)=>`<div class="stat-row"><span>${e(stat.name)}</span><b>${stat.value}</b><div class="stat-track"><i style="width:${Math.min(100,stat.value/255*100)}%;--stat-color:${['#8fae69','#d29b6c','#d2b56d','#8ea6bd','#9bb8a2','#b7a0bb'][index]}"></i></div></div>`).join('')}</div><p class="extra-note">种族值是宝可梦种类的基础能力，不是个体当前的能力值。</p>`;
      }
      if (active === 'acquisition') {
        const rows = extra.acquisition || [], games = [...new Set(rows.map(r=>r.games))];
        const filtered = rows.filter(r=>(!game||r.games===game)&&match([r.games,r.form,r.location,r.method,r.note].join(' ')));
        return `<div class="extra-tools"><label class="extra-select">游戏版本<select id="extra-game"><option value="">全部版本</option>${games.map(g=>`<option ${g===game?'selected':''} value="${e(g)}">${e(g)}</option>`).join('')}</select></label>${search('搜索地点、方式或形态')}</div><div class="extra-count" aria-live="polite">${filtered.length} 条获得记录</div><div class="extra-table-wrap"><table class="extra-table acquisition-table"><thead><tr><th>游戏 / 形态</th><th>地点与方式</th><th>备注</th></tr></thead><tbody>${filtered.map(r=>`<tr><td><b>${e(r.games)}</b><small>${e(r.form)} · 第 ${r.generation} 世代</small></td><td>${e(r.location)}${r.method?`<small>${e(r.method)}</small>`:''}</td><td>${e(r.note||'—')}</td></tr>`).join('')}</tbody></table>${filtered.length?'':empty}</div>`;
      }
      if (active === 'matchups') {
        const groups=extra.matchups||[], group=groups[selected];
        if(!group)return empty;
        return select(groups.map(g=>g.label)) + `<p class="extra-note">受到对应属性招式攻击时的伤害倍率。请留意所选形态、特性及对战规则。</p><div class="matchup-grid">${group.types.map(t=>`<div class="matchup ${t.multiplier==='0'?'immune':t.multiplier.includes('/')?'resist':Number(t.multiplier)>1?'weak':''}">${ui.typeTags([t.name])}<b>${e(t.multiplier)}×</b></div>`).join('')}</div><div class="matchup-legend"><span>橙色 · 弱点</span><span>绿色 · 抵抗</span><span>灰色 · 免疫</span></div>`;
      }
      if (active === 'learn' || active === 'machine') {
        const groups=(extra.movesets||[]).filter(g=>g.kind===active), group=groups[selected];
        if(!group)return empty;
        const filtered=group.moves.filter(m=>match([m.name,m.type,m.category,m.learn].join(' '))), timed=group.moves.some(m=>m.cooldown!=null);
        return `<div class="extra-tools">${select(groups.map(g=>g.game+' · '+g.form+' · '+g.method))}${search(active==='machine'?'搜索招式或学习器编号':'搜索招式、属性或等级')}</div><div class="extra-count" aria-live="polite">${filtered.length} 个招式${timed&&active==='learn'?' · 等级栏依次为等级 / 加强等级':''}</div><div class="extra-table-wrap"><table class="extra-table move-table"><thead><tr><th>${active==='machine'?'学习器':'等级 / 方式'}</th><th>招式</th><th>属性</th><th>分类</th><th>威力</th>${timed?'<th>发动时间</th>':'<th>命中</th><th>PP</th>'}</tr></thead><tbody>${filtered.map(m=>`<tr><td>${e(m.learn||'—')}</td><td>${/^https:\/\/wiki\.52poke\.com\//.test(m.source_url||'')?`<a href="${e(m.source_url)}" target="_blank" rel="noopener noreferrer">${e(m.name)} ↗</a>`:e(m.name)}</td><td>${ui.typeTags([m.type])}</td><td>${e(m.category)}</td><td>${e(m.power)}</td>${timed?`<td>${e(m.cooldown)} 秒</td>`:`<td>${e(m.accuracy)}</td><td>${e(m.pp)}</td>`}</tr>`).join('')}</tbody></table>${filtered.length?'':empty}</div><p class="extra-note">收录源站当前详情页所列版本；各版本的招式表独立展示。</p>`;
      }
      const pairs=extra.shiny_pairs||[], pair=pairs[selected];
      if(!pair)return empty;
      return select(pairs.map(p=>p.game+' · '+p.form)) + `<div class="shiny-comparison"><figure><div class="shiny-photo">${ui.imageMarkup(pair.normal,ui.imageURL(pair.normal),'普通 · '+pair.form)}</div><figcaption>普通</figcaption></figure><figure><div class="shiny-photo">${ui.imageMarkup(pair.shiny,ui.imageURL(pair.shiny),'异色 · '+pair.form)}</div><figcaption>✦ 异色</figcaption></figure></div><p class="extra-note">${e(pair.game)} · ${e(pair.form)} · 同一形态的源站原图</p>`;
    }
    function render(preserveFocus=false) {
      const caret=root.querySelector('#extra-search')?.selectionStart;
      root.innerHTML=`<div class="extra-heading"><div><div class="detail-eyebrow">POKÉMON FIELD GUIDE</div><h3>更深入地认识它</h3></div><span>游戏资料</span></div><div class="extra-tabs" role="tablist" aria-label="宝可梦详细资料">${tabs.map(([key,label])=>`<button role="tab" id="tab-${key}" aria-controls="pokemon-extra-panel" aria-selected="${active===key}" data-extra-tab="${key}" class="${active===key?'active':''}">${label}</button>`).join('')}</div><div id="pokemon-extra-panel" role="tabpanel" aria-labelledby="tab-${active}">${content()}</div>`;
      root.querySelectorAll('[data-extra-tab]').forEach(button=>button.onclick=()=>{active=button.dataset.extraTab;selected=0;query='';game='';render();root.querySelector('#tab-'+active).focus({preventScroll:true});});
      const selection=root.querySelector('#extra-select');if(selection)selection.onchange=()=>{selected=Number(selection.value);query='';render();};
      const gameSelect=root.querySelector('#extra-game');if(gameSelect)gameSelect.onchange=()=>{game=gameSelect.value;render();};
      const input=root.querySelector('#extra-search');if(input)input.oninput=()=>{query=input.value;render(true);};
      if(preserveFocus&&input){input.focus({preventScroll:true});try{input.setSelectionRange(caret,caret);}catch(_){}}
      ui.bindImages(root);
    }
    render();
  }
};
