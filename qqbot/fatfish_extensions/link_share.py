"""Share source pages instead of downloading and encoding requested music."""
import asyncio
import contextvars

EVIDENCE = contextvars.ContextVar("search_link_evidence", default=())
import re
import time
from urllib.parse import quote,urlsplit


def song_url(source, candidate):
    sid=str(candidate.get('bvid') or candidate.get('id') or '')
    if source=='netease' and sid.isdigit():return 'https://music.163.com/song?id='+sid
    if source=='qq' and re.fullmatch(r'[A-Za-z0-9]+',sid):return 'https://y.qq.com/n/ryqq/songDetail/'+sid
    if source=='kugou' and re.fullmatch(r'[A-Fa-f0-9]{32}',sid):return 'https://www.kugou.com/song/#hash='+sid
    if source=='bili' and re.fullmatch(r'BV[0-9A-Za-z]{10}|av[0-9]+',sid):return 'https://www.bilibili.com/video/'+sid
    if source=='youtube' and re.fullmatch(r'[A-Za-z0-9_-]{11}',sid):return 'https://www.youtube.com/watch?v='+sid
    return ''


def find_song(music, request, sessdata='', log=print):
    title,artist=music.parse(request)
    if not title:return None
    # Match the configured order exactly; don't download, probe playback or convert audio.
    for source in music._cfg_sources():
        try:
            _,candidates=music._search(source,title,artist,request,sessdata,False,(),log)
            for item in candidates:
                url=song_url(source,item)
                if url:
                    name=item.get('name') or item.get('title') or title
                    return {'url':url,'title':name,'source':music.SRC_NAME[source]}
        except Exception as error:
            log('[分享链接]',source,type(error).__name__)
    return None


def install_bot(module):
    music = getattr(module, "music", None)
    if music is None:
        import importlib
        music = importlib.import_module("music")
    async def share(self,scene,target,conv,req,reply_to=None,said='',info=None,quiet=False,ctx=None,*,full=False):
        if isinstance(info,dict):info['sung']=False
        if scene=='group' and module.control.group_mode(target)=='mute':return None
        if not full:
            permit=module.sing._permits.get(conv) or {}
            if permit.get('until',0)<time.time() or permit.get('left',0)<=0:return None
            permit['left']-=1
        name=str(req.get('name') or '') if isinstance(req,dict) else str(req or '')
        got=await asyncio.to_thread(find_song,music,name,module.sing.SESSDATA.get('v',''),module.log)
        if ctx is not None and self._halted(conv,scene,ctx):return None
        if not got:
            if quiet:return None
            line='设置的找歌来源中没有找到可确认的歌曲链接，请补充歌名和歌手。'
        else:line=f"{got['source']} · {got['title']}\n{got['url']}"
        result=await self._send('send_group_msg' if scene=='group' else 'send_private_msg','group_id' if scene=='group' else 'user_id',target,[{'type':'text','data':{'text':line}}])
        return line if result.get('retcode')==0 else None
    module.FatFish._sing=share
    async def full(self,scene,target,conv,req,uid,name,after,t0=None):
        try:return await share(self,scene,target,conv,req,full=True)
        finally:
            module.sing.full_end(uid,conv)
            module.sing.full_job_end(conv,uid)
    module.FatFish._sing_full=full


def guarded_reply(segments, query):
    """Never let the language model invent a requested share URL or video facts."""
    requested_video = bool(re.search(r'(?i)(b站|哔哩|bilibili)',query) and re.search(r'视频|最新|链接|分享|找|搜',query))
    text = '\n'.join(x for x in segments if isinstance(x,str))
    urls = re.findall(r'https?://[^\s<>）)\]，。]+',text)
    evidence = EVIDENCE.get()
    valid = [r for r in evidence if re.fullmatch(r'https://www\.bilibili\.com/video/(?:BV[0-9A-Za-z]{10}|av[0-9]+)',str(r.get('url') or ''))]
    if requested_video:
        if not valid:return ['这次没有查到可核实的B站视频链接，暂时不能确认标题或最新一期。']
        lines=['找到的B站视频（搜索结果，未确认是该作者最新一期）：']
        for result in valid[:3]:
            lines.append(str(result.get('title') or '视频') + (' · ' + str(result['date']) if result.get('date') else '') + '\n' + result['url'])
        return ['\n'.join(lines)]
    known={str(r.get('url')) for r in evidence}
    if urls and any(url not in known for url in urls):
        return ['这次没有查到能核实的分享链接，不能提供未经确认的地址。']
    return segments


def install():
    import websearch
    if getattr(websearch,'_atlas_links',False):return
    original=websearch.block
    original_bili=websearch._bili
    original_search=websearch.search
    def block(found):
        found=list(found)
        EVIDENCE.set(tuple(r for _,results in found for r in results if isinstance(r,dict)))
        text=original(found).replace('别贴链接','分享已核实结果时附对应链接')
        links=[]
        for query,results in found:
            for result in results:
                url=str(result.get('url') or '')
                if urlsplit(url).scheme in {'https','http'}:
                    links.append(str(result.get('title') or '')+' '+url)
        if links:text+='\n可分享的真实来源链接（只使用对应结果，不编造地址；用户要视频、歌曲或链接时必须附上）：\n'+'\n'.join(links[:8])+'\n无法从搜索结果确认最新或发布时间时，不得声称这是最新视频。\n'
        return text
    websearch.block=block
    # Public Bili search drops bvid/url, so preserve the actual result URLs.
    async def bili(client,query):
        import hashlib,json
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from urllib.parse import urlencode
        headers={'Referer':'https://www.bilibili.com/'}
        nav=(await client.get('https://api.bilibili.com/x/web-interface/nav',headers=headers)).json()
        w=(nav.get('data') or {}).get('wbi_img') or {}
        raw=w['img_url'].rsplit('/',1)[-1].split('.')[0]+w['sub_url'].rsplit('/',1)[-1].split('.')[0]
        mix=''.join(raw[i] for i in websearch.MIXIN)[:32]
        params={'search_type':'video','keyword':query,'page':1,'wts':int(time.time())}
        if '最新' in query:params['order']='pubdate'
        encoded=urlencode({k:re.sub(r"[!'()*]",'',str(v)) for k,v in sorted(params.items())})
        signature=hashlib.md5((encoded+mix).encode()).hexdigest()
        data=(await client.get('https://api.bilibili.com/x/web-interface/wbi/search/type?'+encoded+'&w_rid='+signature,headers=headers)).json()
        if data.get('code')!=0:raise RuntimeError('B站搜索未成功')
        results=[]
        for value in (data.get('data') or {}).get('result',[])[:6]:
            url=song_url('bili',value)
            if not url:continue
            results.append({'title':websearch._strip(value.get('title') or ''),'url':url,'snippet':websearch._strip(value.get('description') or '')[:150], 'date':datetime.fromtimestamp(value['pubdate'],ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d') if value.get('pubdate') else '', 'site':'B站'})
        return results
    async def search(query, log=print, want=8, ori=None):
        if re.search(r'(?i)b站|哔哩|bilibili',str(query)+' '+str(ori or '')):
            client=await websearch.client()
            try:
                results=await bili(client,query)
            except Exception as error:
                log('[分享链接] B站搜索失败',type(error).__name__)
                return []
            return [dict(result,src='B站') for result in results[:want]]
        return await original_search(query,log,want,ori)
    websearch.search=search
    websearch._bili=bili
    websearch.SOURCES=[(name,bili if fn is original_bili else fn) for name,fn in websearch.SOURCES]
    websearch._atlas_links=True
