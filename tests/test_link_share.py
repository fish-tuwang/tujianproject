import asyncio
import time
from types import SimpleNamespace
from qqbot.fatfish_extensions.link_share import find_song, song_url, install_bot


def test_configured_source_order_and_no_audio_download():
    calls=[]
    def search(source,*args):
        calls.append(source)
        if source=='netease':return [],[]
        return [],[{'bvid':'BV1234567890','title':'Lemon'}]
    music=SimpleNamespace(parse=lambda req:('Lemon','米津玄师'),_cfg_sources=lambda:['netease','bili','qq'],_search=search,SRC_NAME={'bili':'B站'})
    got=find_song(music,'Lemon - 米津玄师',log=lambda *a:None)
    assert calls==['netease','bili']
    assert got['url']=='https://www.bilibili.com/video/BV1234567890'
    assert song_url('netease',{'id':123})=='https://music.163.com/song?id=123'
    assert song_url('bili',{'bvid':'javascript:bad'})==''


def test_share_uses_text_only_and_cancels_before_send():
    calls=[]
    class Bot:
        async def _send(self,*args):calls.append(args);return {'retcode':0}
        def _halted(self,*args):return True
    sing=SimpleNamespace(_permits={'g':{'until':time.time()+90,'left':2}},SESSDATA={'v':''})
    music=SimpleNamespace(parse=lambda req:(req,''),_cfg_sources=lambda:['netease'],_search=lambda *a:([],[{'id':123,'name':'测试歌'}]),SRC_NAME={'netease':'网易云'})
    module=SimpleNamespace(FatFish=Bot,sing=sing,music=music,control=SimpleNamespace(group_mode=lambda t:'normal'),log=lambda *a:None)
    install_bot(module)
    result=asyncio.run(Bot()._sing('group',1,'g',{'name':'测试歌'}))
    assert result.endswith('https://music.163.com/song?id=123')
    assert calls[0][-1][0]['type']=='text'
    asyncio.run(Bot()._sing('group',1,'g',{'name':'测试歌'},ctx={}))
    assert len(calls)==1


def test_bili_results_retain_share_url_and_latest_sort(monkeypatch):
    import sys
    from qqbot.fatfish_extensions.link_share import install
    old_bili=lambda *a:None
    fake=SimpleNamespace(block=lambda found:'别贴链接',MIXIN=list(range(64)),_strip=lambda x:x,_bili=old_bili,SOURCES=[('B站',old_bili)],search=lambda *a:None)
    monkeypatch.setitem(sys.modules,'websearch',fake)
    install()
    urls=[]
    class Client:
        async def get(self,url,**kwargs):
            urls.append(url)
            if 'nav' in url:
                data={'data':{'wbi_img':{'img_url':'https://example.com/'+'a'*32+'.png','sub_url':'https://example.com/'+'b'*32+'.png'}}}
            else:data={'code':0,'data':{'result':[{'bvid':'BV1234567890','title':'视频','pubdate':1795500000}]}}
            return SimpleNamespace(json=lambda:data)
    assert fake.SOURCES[0][1] is fake._bili
    found=asyncio.run(fake.SOURCES[0][1](Client(),'作者 最新视频'))
    assert 'order=pubdate' in urls[-1]
    assert found[0]['url']=='https://www.bilibili.com/video/BV1234567890'
    text=fake.block([('query',found)])
    assert found[0]['url'] in text and '别贴链接' not in text


def test_fake_links_and_latest_titles_cannot_reach_qq():
    from qqbot.fatfish_extensions.link_share import EVIDENCE,guarded_reply
    token=EVIDENCE.set(())
    try:
        fake=['最新视频是《随便编一个标题》 https://space.bilibili.com/XXXXXX']
        blocked=guarded_reply(fake,'去B站找鲁大能最新视频发给我')
        assert 'XXXXXX' not in str(blocked) and '随便编一个标题' not in str(blocked)
        assert '没有查到' in blocked[0]
        EVIDENCE.set(({'title':'真实搜索标题','url':'https://www.bilibili.com/video/BV1234567890','date':'2026-11-24'},))
        result=guarded_reply(fake,'B站最新视频')
        assert '真实搜索标题' in result[0] and 'BV1234567890' in result[0]
        assert 'XXXXXX' not in result[0] and '未确认' in result[0]
        EVIDENCE.set(())
        assert '不能提供' in guarded_reply(['https://music.163.com/song?id=123'],'发个链接')[0]
    finally:EVIDENCE.reset(token)
