import json
from pathlib import Path
import shutil
import subprocess

import pytest
from qqbot.fatfish_extensions.panel_ui import enhance_sticker_ui


def test_selection_preserves_images_and_sends_latest_sticker(tmp_path):
    node=shutil.which('node')
    if not node:pytest.skip('Node required for browser handler regression')
    native=(Path(__file__).parent/'fixtures/fatfish_send_view.js').read_text()
    patched=enhance_sticker_ui(native)
    script=tmp_path/'check.cjs'
    script.write_text('const source='+json.dumps(patched)+';\n'+r'''
const assert=require('node:assert/strict');
const VIEWS={}, nodes={}, calls=[];
const $=s=>nodes[s] ||= {value:'',checked:false,textContent:'',setAttribute(){},removeAttribute(){}};
const document={querySelector:()=>({value:'group'}),querySelectorAll:()=>[]};
let builds=0,cards=[];
Object.defineProperty($('#sg'),'innerHTML',{set(html){builds++;cards=[...html.matchAll(/data-n="([^"]+)"/g)].map(m=>({dataset:{n:m[1]},image:{},picked:false,classList:{toggle(k,v){this.owner.picked=v;}}}));cards.forEach(c=>c.classList.owner=c);}});
$('#sg').querySelectorAll=()=>cards;
const esc=s=>s,hm=s=>s,toast=()=>{},setTimeout=()=>{};
const stickers=async()=>[{name:'困A',file:'a.png',emo:'困',scene:''},{name:'困B',file:'b.png',emo:'困',scene:''}];
const api=async(path,body)=>{calls.push({path,body});if(path==='/api/people')return {groups:[],friends:[]};return {ok:true,data:{history:[]}};};
eval(source);
(async()=>{
 await VIEWS.send({set innerHTML(value){}});
 const original=cards,images=cards.map(c=>c.image),initial=builds;
 const tap=n=>$('#sg').onclick({target:{closest:()=>cards[n]}});
 tap(0);assert.equal(cards[0].picked,true);
 tap(1);assert.equal(cards[0].picked,false);assert.equal(cards[1].picked,true);
 tap(1);assert.equal(cards[1].picked,false);assert.equal($('#picked').textContent,'没选表情包');
 for(let i=0;i<20;i++)tap(i%2);
 assert.equal(cards,original);assert.deepEqual(cards.map(c=>c.image),images);assert.equal(builds,initial);
 assert.equal(calls.filter(c=>c.body).length,0);
 $('#tgt2').value='123456';
 await $('#go').onclick();
 assert.equal(calls.find(c=>c.path==='/api/send').body.sticker,'困B');
 assert.equal(builds,initial);assert.ok(cards.every(c=>!c.picked));
 $('#sq').value='困A';$('#sq').oninput();assert.equal(cards.length,1);
 console.log('selection, deselection, rapid taps, send reset, search passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
''')
    result=subprocess.run([node,str(script)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr


def test_native_upstream_patch_is_idempotent():
    native=(Path(__file__).parent/'fixtures/fatfish_send_view.js').read_text()
    patched=enhance_sticker_ui(native)
    assert patched!=native
    assert enhance_sticker_ui(patched)==patched


def test_toggle_keeps_other_images_and_ignores_duplicate_taps(tmp_path):
    node=shutil.which('node')
    if not node:pytest.skip('Node required for browser handler regression')
    native=(Path(__file__).parent/'fixtures/fatfish_send_view.js').read_text()
    script=tmp_path/'toggle.cjs'
    script.write_text('const source='+json.dumps(enhance_sticker_ui(native))+';\n'+r'''
const assert=require('node:assert/strict'),VIEWS={},nodes={};let STK=null,builds=0,cards=[],requests=0,resolve;
const $=s=>nodes[s] ||= {value:'',textContent:''};
Object.defineProperty($('#g'),'innerHTML',{set(html){builds++;cards=[...html.matchAll(/data-n="([^"]+)"/g)].map(m=>({dataset:{n:m[1]},image:{},meta:{},classList:{toggle(){}},querySelector(){return this.meta;},remove(){cards=cards.filter(c=>c!==this);}}));}});
const esc=s=>s,toast=()=>{};
const S=[{name:'A',file:'a.png',emo:'困',scene:'',off:false},{name:'B',file:'b.png',emo:'困',scene:'',off:false}];
const stickers=async()=>S;
const api=()=>{requests++;return new Promise(r=>resolve=r);};
eval(source);
(async()=>{
 await VIEWS.stickers({set innerHTML(value){}});
 const original=cards,images=cards.map(c=>c.image),initial=builds;
 const event={target:{closest:()=>cards[0]}};
 const first=$('#g').onclick(event);await $('#g').onclick(event);
 assert.equal(requests,1);resolve({ok:true});await first;
 assert.equal(S[0].off,true);assert.equal(cards,original);assert.deepEqual(cards.map(c=>c.image),images);assert.equal(builds,initial);
 $('#st').value='off';$('#st').oninput();assert.equal(cards.length,1);
 const filtered=builds;const second=$('#g').onclick({target:{closest:()=>cards[0]}});resolve({ok:true});await second;
 assert.equal(S[0].off,false);assert.equal(cards.length,0);assert.equal(builds,filtered);assert.equal($('#cnt').textContent,'0 张');
 console.log('toggle, duplicate tap, filtered removal passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
''')
    result=subprocess.run([node,str(script)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
