"""Manage local emotion events, diaries and self notes alongside native memory pages."""
import json
from pathlib import Path

from . import common,memory,mood,soul,VERSION
from .panel_ui import enhance_sticker_ui
from .usage_ui import enhance_usage_ui
from . import usage


def snapshot():
    counts={'active':0,'archived':0,'conversations':0}
    for path in (common.DATA/'memory').glob('*.json'):
        value=common.read(path,{})
        counts['conversations']+=1
        for fact in value.get('facts',[]):
            key='active' if fact.get('status','active')=='active' else 'archived';counts[key]+=1
    return {'ok':True,'version':VERSION,'mood':mood.current(),'label':mood.label(),'memory':counts,
            'diary':soul.load_diary()['entries'],'self_notes':common.read(common.DATA/'self-notes.json',{'entries':[]})['entries']}


def manage(body):
    action=body.get('action')
    if action=='reset_mood':mood.reset();return {'ok':True}
    if action=='self_add':return {'ok':bool(soul.add_self(str(body.get('text',''))))}
    if action in {'self_remove','diary_archive','event_remove'}:
        name,key={'self_remove':('self-notes.json','entries'),'diary_archive':('diary.json','entries'),'event_remove':('mood2.json','timeline')}[action]
        token=str(body.get('id',''))
        def change(value):
            entries=value.get(key,[]);found=[e for e in entries if str(e.get('id') or e.get('ts'))==token]
            if not found:return False
            # Management is reversible: removed entries remain in a private archive.
            archive=value.setdefault('removed',[]);archive.extend(found)
            value[key]=[e for e in entries if e not in found];return True
        return {'ok':bool(common.edit(name,change))}
    return {'ok':False,'error':'未知操作'}


HTML='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>哦鲸鲸 · 记忆与心情</title><style>STYLE
body{padding:24px;max-width:1100px;margin:auto}header{display:flex;align-items:center;gap:20px;margin-bottom:24px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}.card{padding:22px;background:var(--panel);border:1px solid var(--line);border-radius:14px}li{margin:12px 0;white-space:pre-wrap;overflow-wrap:anywhere}button{cursor:pointer;margin-left:12px}textarea{width:100%;min-height:90px}#message{min-height:24px;color:var(--accent)}@media(max-width:700px){.grid{grid-template-columns:1fr}}</style><body>
<header><a href="/">← 返回控制台</a><h1>记忆与心情</h1></header><p>记忆按QQ号归属，心情会逐渐回落；历史记录不会当作系统指令。管理操作会保留本机可恢复归档。</p><p id="message" role="status"></p>
<div class="grid"><section class="card"><h2>记忆概况</h2><div id="memory"></div><p><a href="/#memory">查看、添加与删除记忆</a> · <a href="/#memory">钉住与遗忘曲线</a> · <a href="/#memory">关系管理</a></p></section><section class="card"><h2>当前心情</h2><div id="mood"></div><button data-action="reset_mood">恢复平静</button></section>
<section class="card"><h2>最近互动与情绪</h2><ul id="events"></ul></section><section class="card"><h2>本机日记</h2><p>只根据真实互动记录，不自动发到群或空间。</p><ul id="diary"></ul></section><section class="card"><h2>自我笔记</h2><ul id="notes"></ul><textarea id="note" aria-label="自我笔记" maxlength="160" placeholder="添加一条偏好或自我笔记"></textarea><button data-action="self_add">保存笔记</button></section></div>
<script>
const el=id=>document.getElementById(id);const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const row=(entry,text,action)=>'<li>'+esc(text)+'<button data-action="'+action+'" data-id="'+esc(entry.id||entry.ts)+'">移入归档</button></li>';
async function load(){try{const r=await fetch('/api/local-core',{cache:'no-store'});if(!r.ok)throw Error('读取失败');const d=await r.json();el('memory').textContent='活动记忆 '+d.memory.active+' 条 · 已归档 '+d.memory.archived+' 条 · '+d.memory.conversations+' 个对话';el('mood').textContent=d.label+' · '+d.mood.mood.toFixed(1)+'/100（内部状态，不代表对用户的评价）';el('events').innerHTML=d.mood.timeline.slice(-20).reverse().map(e=>row(e,new Date(e.ts*1000).toLocaleString('zh-CN')+' '+(e.what||e.event||''),'event_remove')).join('')||'<li>等待新的真实互动；不会预填虚假心情事件。</li>';el('diary').innerHTML=d.diary.slice(-14).reverse().map(e=>row(e,e.day+' '+e.text,'diary_archive')).join('')||'<li>有真实互动后，在设定时段生成日记。</li>';el('notes').innerHTML=d.self_notes.map(e=>row(e,e.text,'self_remove')).join('')||'<li>暂无自我笔记。</li>';}catch(e){el('message').textContent=e.message;}}
document.addEventListener('click',async e=>{const b=e.target.closest('[data-action]');if(!b)return;b.disabled=true;try{const r=await fetch('/api/local-core',{method:'POST',headers:{'Content-Type':'application/json','X-Panel':'1'},body:JSON.stringify({action:b.dataset.action,id:b.dataset.id,text:el('note').value})});const d=await r.json();if(!r.ok||!d.ok)throw Error(d.error||'操作未完成');el('message').textContent='已保存';if(b.dataset.action==='self_add')el('note').value='';await load();}catch(e){el('message').textContent=e.message;}finally{b.disabled=false;}});load();
</script></body></html>'''


def install(panel):
    usage.install_panel(panel)
    original_get=panel.H.do_GET;original_route=panel.H.route;original_file=panel.H._file
    def get(self):
        if not self._host_ok():return self._json({'ok':False},403)
        path=self.path.split('?',1)[0]
        if path=='/api/model-usage':
            from urllib.parse import parse_qs,urlsplit
            try:return self._json(usage.snapshot(int(parse_qs(urlsplit(self.path).query).get('days',['30'])[0])))
            except (ValueError,TypeError,OSError):return self._json({'ok':False,'error':'模型用量读取失败，未用默认价格替代'},503)
        if path=='/api/local-core':return self._json(snapshot())
        if path=='/local-core':
            native=Path(panel.HTML).read_text();style=native.split('<style>',1)[1].split('</style>',1)[0]
            body=HTML.replace('STYLE',style,1).encode();self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body);return
        return original_get(self)
    def route(self,path,body):return manage(body) if path=='/api/local-core' else original_route(self,path,body)
    def file(self,path,ctype=None,cache=True):
        if Path(path)==Path(panel.HTML):
            body=enhance_usage_ui(enhance_sticker_ui(Path(path).read_text())).replace('<nav aria-label="控制台页面">','<nav aria-label="控制台页面"><a style="padding:14px" href="/local-core">记忆与心情管理 ↗</a>',1).encode()
            self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body);return
        return original_file(self,path,ctype,cache)
    panel.H.do_GET=get;panel.H.route=route;panel.H._file=file
