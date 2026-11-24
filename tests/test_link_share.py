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
    fake=SimpleNamespace(block=lambda found:'别贴链接',MIXIN=list(range(64)),_strip=lambda x:x)
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
    found=asyncio.run(fake._bili(Client(),'作者 最新视频'))
    assert 'order=pubdate' in urls[-1]
    assert found[0]['url']=='https://www.bilibili.com/video/BV1234567890'
    text=fake.block([('query',found)])
    assert found[0]['url'] in text and '别贴链接' not in text
