"""Provider-neutral model billing views for the native FatFish panel."""
import re

VIEW=r'''
async function atlasModelUsage(main, activity=false){
 main.innerHTML='<h1>'+ (activity?'统计':'模型用量与费用')+'</h1><p class="sub">按实际 API 返回的模型和 Token 统计；费用为官方单价估算，最终扣费以百炼账单为准。</p><div class="row" style="margin-bottom:12px">'+[1,7,30,90].map(n=>'<button class="chip" data-days="'+n+'">'+(n===1?'今天':n+' 天')+'</button>').join('')+'</div><div id="model-usage-body">读取中…</div>';
 const draw=async days=>{
  const d=await api('/api/model-usage?days='+days);const box=main.querySelector('#model-usage-body');
  if(!d.ok){box.textContent=d.error||'模型统计暂时不可用';return;}
  const rows=d.models||[],sum=k=>rows.reduce((n,r)=>n+Number(r[k]||0),0),missing=sum('unpriced_calls');
  const active=d.active||{},amount=v=>'¥'+Number(v||0).toFixed(6);
  box.innerHTML='<div class="card"><h2>当前模型：'+esc(active.model)+' <span class="badge">'+esc(active.provider)+'</span></h2><p class="small muted">逐次记录实际返回的模型，切换模型后分别统计；千问不套用 DeepSeek 峰谷价格。</p><div class="row" style="flex-wrap:wrap;gap:18px"><b>'+sum('calls')+' 次调用</b><span>输入 '+num(sum('input'))+' Token（其中缓存命中 '+num(sum('cached'))+'）</span><span>输出 '+num(sum('output'))+' Token（含思考 '+num(sum('reasoning'))+'）</span><b>已知单价估算 '+amount(sum('cost_cny'))+'</b></div>'+(missing?'<p class="small">另有 '+missing+' 次调用缺少已核对单价或 usage，费用未计入上述小计。</p>':'')+'<p class="small muted">'+esc(d.note)+'</p><a href="https://bailian.console.aliyun.com/" target="_blank" rel="noopener">去百炼控制台核对账单和余额 ↗</a> · <a href="'+esc(d.price_source)+'" target="_blank" rel="noopener">官方价格依据 ↗</a></div>'
  +'<div class="card"><h2>按实际模型 / 计费档位</h2><div style="overflow:auto"><table><tr><th>模型</th><th>模式/档位</th><th>调用</th><th>输入</th><th>缓存命中</th><th>输出/思考</th><th>单价 ¥/百万</th><th>估算费用</th></tr>'+rows.map(r=>'<tr><td>'+esc(r.model)+'</td><td>'+(r.price?(r.price.thinking?'思考':'非思考')+' / ≤'+num(r.price.tier_max_input):'单价未确认')+'</td><td>'+num(r.calls)+'</td><td>'+num(r.input)+'</td><td>'+num(r.cached)+'</td><td>'+num(r.output)+' / '+num(r.reasoning)+'</td><td>'+(r.price?[r.price.input_per_million,r.price.cached_per_million,r.price.output_per_million].join(' / '):'—')+'</td><td>'+(r.unpriced_calls===r.calls?'未计价':amount(r.cost_cny))+'</td></tr>').join('')+'</table></div>'+(!rows.length?'<p class="muted">新版启用后有实际模型调用才开始记录，不填充模拟消耗。</p>':'')+'</div>'
  +'<div class="card"><h2>按功能</h2><table><tr><th>模型</th><th>功能</th><th>调用</th><th>输入/缓存/输出</th><th>估算费用</th></tr>'+rows.flatMap(r=>Object.entries(r.by||{}).map(([tag,x])=>'<tr><td>'+esc(r.model)+'</td><td>'+esc(tag)+'</td><td>'+num(x.calls)+'</td><td>'+num(x.input)+' / '+num(x.cached)+' / '+num(x.output)+'</td><td>'+(x.unpriced_calls===x.calls?'未计价':amount(x.cost_cny))+'</td></tr>')).join('')+'</table></div>'
  +'<div class="card"><h2>每日模型消耗</h2><table><tr><th>日期</th><th>调用</th><th>输入/缓存/输出</th><th>已知单价估算</th></tr>'+(d.daily||[]).slice().reverse().map(x=>'<tr><td>'+esc(x.day)+'</td><td>'+num(x.calls)+'</td><td>'+num(x.input)+' / '+num(x.cached)+' / '+num(x.output)+'</td><td>'+amount(x.cost_cny)+(x.unpriced_calls?'（部分未计价）':'')+'</td></tr>').join('')+'</table><p class="small muted">历史旧统计另有 '+num(d.legacy_unattributed_calls)+' 次调用缺少模型、单次上下文档位或缓存资料，保留记录，不按当前模型追溯伪造费用。这里为模型费用，不含语音、动画等外部服务费用。</p></div><div id="model-activity"></div>';
  if(activity){const s=await api('/api/stats?days='+days),t=s.total||{};main.querySelector('#model-activity').innerHTML='<div class="card"><h2>聊天与工具计数</h2><p>收到 '+num((t.recv_group||0)+(t.recv_private||0))+' · 回复 '+num((t.replies_group||0)+(t.replies_private||0))+' · 表情 '+num(t.stickers)+' · 语音 '+num(t.voice)+' · 语音字数 '+num(t.voice_chars)+'</p><h2>心情曲线</h2><div id="model-mood"></div></div>';if(s.mood&&s.mood.length)linechart(main.querySelector('#model-mood'),moodPts(s.mood));}
 };
 main.querySelectorAll('[data-days]').forEach(b=>b.onclick=()=>draw(Number(b.dataset.days)));
 await draw(1);
}
VIEWS.usage=async main=>atlasModelUsage(main,false);
VIEWS.stats=async main=>atlasModelUsage(main,true);
'''


def enhance_usage_ui(html):
    # Replace the two view definitions in place, before the native initial render.
    for name in ['usage','stats']:
        html=re.sub(r'VIEWS\.'+name+r' = async main => \{.*?\n\};',
                    'VIEWS.'+name+' = async main => atlasModelUsage(main,'+('true' if name=='stats' else 'false')+');',html,flags=re.S)
    if 'async function atlasModelUsage(' not in html:
        html=html.replace('const CUR =',VIEW+'\nconst CUR =',1)
    # The backend keeps this wire key for old clients; the balance is never faked.
    html=html.replace('"DeepSeek 余额"','"模型账单"').replace('DeepSeek 官方余额接口 5 分钟查一次','实际账单请到对应模型平台核对')
    html=html.replace('今天大概花了','已追踪模型估算').replace('一共大概花了','已追踪模型估算')
    return html
