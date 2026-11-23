import json
import re
import shutil
import subprocess
from types import SimpleNamespace
import pytest
from backend.app.qq_panel import QQ_LOGIN_HTML
from qqbot import fatfish_mac


def test_current_qr_reads_container_not_stale_host_copy(tmp_path,monkeypatch):
    monkeypatch.setattr(fatfish_mac,'ROOT',tmp_path/'fatfish')
    (tmp_path/'login-qr.png').write_bytes(b'stale-host-copy')
    import io
    from PIL import Image
    output=io.BytesIO();Image.new('RGB',(8,8),'black').save(output,format='PNG')
    fresh=output.getvalue();calls=[]
    def run(args,**kwargs):calls.append(args);return SimpleNamespace(returncode=0,stdout=fresh)
    monkeypatch.setattr(fatfish_mac.subprocess,'run',run)
    assert fatfish_mac.current_login_qr()==fresh
    assert calls==[['docker','exec','little-atlas-mac-qq-account-1','cat','/app/napcat/cache/qrcode.png']]
    assert (tmp_path/'login-qr.png').read_bytes()==b'stale-host-copy'


def test_qr_reader_rejects_error_or_invalid_image(monkeypatch):
    for code,data in [(1,b''),(0,b'not png')]:
        monkeypatch.setattr(fatfish_mac.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=code,stdout=data))
        with pytest.raises(ValueError):fatfish_mac.current_login_qr()


def test_login_page_automatically_shows_authenticated_qr_and_handles_expired_session(tmp_path):
    node=shutil.which('node')
    if not node:pytest.skip('Node required for QR display regression')
    code=re.search(r'<script>(.*?)</script>',QQ_LOGIN_HTML,re.S).group(1)
    script=tmp_path/'qr.cjs'
    script.write_text(r'''
const assert=require('node:assert/strict'),nodes={};let expired=false;const sources=[],requests=[];
const document={getElementById:id=>nodes[id] ||= {hidden:true,textContent:'',disabled:false}};
const image=document.getElementById('qr');
Object.defineProperty(image,'src',{set(value){sources.push(value);queueMicrotask(()=>image.onload?.());},get(){return sources.at(-1);}});
const setInterval=()=>{};const confirm=()=>{throw Error('QR refresh must not block on a browser modal');};
const fetch=async(url,options={})=>{
 requests.push({url,options});
 if(expired)return {ok:false,json:async()=>({code:'AUTH_REQUIRED'})};
 return {ok:true,json:async()=>url.includes('mac-qq-login')?{ok:true,img:'data:image/png;base64,placeholder'}:{state:'scan',checked_at:100,guard:{},delivery:{}}};
};
'''+code+r'''
(async()=>{
 await new Promise(setImmediate);
 assert.equal(image.hidden,false);assert.ok(sources[0].startsWith('/qq-panel/qrcode?t='));
 assert.equal(sources.some(x=>x.startsWith('blob:')||x.startsWith('data:')),false);
 await nodes.refresh.onclick();assert.ok(sources.length>=2);assert.equal(nodes.refresh.disabled,false);
 assert.equal(requests.find(x=>x.options.method==='POST').options.headers['X-Panel-Confirm'],'1');
 expired=true;await status();assert.equal(image.hidden,true);assert.equal(nodes['login-again'].hidden,false);
 assert.ok(nodes.status.textContent.includes('图鉴登录已失效'));
 console.log('automatic QR, explicit refresh, same origin and session expiry passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
''')
    result=subprocess.run([node,str(script)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert 'img[hidden]{display:none}' in QQ_LOGIN_HTML
