"""Keep NetEase transport failures separate from strict song/artist filtering."""
import contextvars
import time
from . import common

_last=contextvars.ContextVar('netease_search_diagnostic',default=None)


def save(value):
    value={'checked_at':time.time(),**value}
    _last.set(value)
    try:common.edit('music-search-status.json',lambda state:state.update(netease=value))
    except (OSError,ValueError,TypeError):pass
    return value


def latest():
    try:return common.read(common.DATA/'music-search-status.json',{}).get('netease',{})
    except (OSError,ValueError,TypeError):return {'why':'搜索诊断记录暂不可读，搜索结果尚未确认'}


def install():
    import music
    if getattr(music,'_atlas_search',False):return
    required=['ne_search','_search','selftest','sources_status','_ne_headers','_login_cookies','_http','_ok_name','_artist_ok','_NE','ABROAD_HOLD','LIVE','ne_abroad']
    if not all(hasattr(music,key) for key in required):raise RuntimeError('upstream_music_interface_changed')
    music._atlas_search=True
    def search(title,artist,client=None,log=print):
        diag={'login_used':False,'raw_count':0,'matched_count':0,'title_rejected':0,'artist_rejected':0,'invalid_count':0,'search_ok':False}
        def failure(code,why,**extra):
            value=save({**diag,**extra,'code':code,'why':why});log('[唱歌] 网易云：'+value['why']);return []
        if music.ne_abroad():return failure('abroad_cooldown','网易云此前明确返回 abroad，当前处于来源冷却期')
        ck=music._login_cookies('netease');headers=music._ne_headers(ck)
        diag['login_used']=bool(ck.get('MUSIC_U') and ck['MUSIC_U'] in headers.get('Cookie',''))
        try:
            response=music._http('GET','https://music.163.com/api/search/get/web',params={'s':f'{title} {artist}'.strip(),'type':1,'offset':0,'limit':15},headers=headers)
            diag['http_status']=response.status_code
            if response.status_code!=200:return failure('http_error','搜索接口 HTTP '+str(response.status_code)+'，不能据此判断歌曲是否存在')
            payload=response.json()
        except (ValueError,TypeError):return failure('invalid_json','搜索接口没有返回可解析的JSON')
        except Exception:return failure('request_failed','搜索请求连接失败或超时，未判断歌曲是否存在')
        if not isinstance(payload,dict):return failure('invalid_response','搜索响应结构异常')
        api_code=payload.get('code');diag['api_code']=api_code if isinstance(api_code,(int,str)) and len(str(api_code))<12 else None
        if payload.get('abroad'):
            music._NE['abroad_until']=time.time()+music.ABROAD_HOLD
            return failure('abroad_response','平台明确返回 abroad 搜索限制，未判断歌曲权限')
        if api_code not in (None,200,'200'):return failure('api_rejected','搜索接口拒绝请求，业务码 '+str(diag['api_code'])+'；未退出账号或改动凭据')
        result=payload.get('result')
        if not isinstance(result,dict):return failure('invalid_result','搜索result结构异常，不等于零首歌曲')
        songs=result.get('songs',[])
        if not isinstance(songs,list):return failure('invalid_songs','搜索songs结构异常')
        diag.update(search_ok=True,raw_count=len(songs))
        candidates=[]
        for song in songs:
            if not isinstance(song,dict):diag['invalid_count']+=1;continue
            artists=[a.get('name') or '' for a in song.get('artists') or song.get('ar') or [] if isinstance(a,dict)]
            if not music._ok_name(song.get('name'),title,f'{title} {artist}'):diag['title_rejected']+=1;continue
            if not music._artist_ok(artists,artist):diag['artist_rejected']+=1;continue
            try:duration=float(song.get('duration') or song.get('dt') or 0)/1000
            except (TypeError,ValueError):diag['invalid_count']+=1;continue
            candidates.append({'id':song.get('id'),'name':song.get('name'),'artists':artists,'dur':duration,'fee':song.get('fee')})
        diag['matched_count']=len(candidates)
        if not songs:return failure('empty_results','搜索接口正常，但本次返回0条歌曲',search_ok=True)
        if not candidates:
            return failure('no_matching_original',f"搜索正常：返回{len(songs)}条，未匹配指定原唱（歌名/版本排除{diag['title_rejected']}条，歌手不符{diag['artist_rejected']}条）；不代表整个来源不可用",search_ok=True)
        logged=bool(ck.get('MUSIC_U'))
        candidates.sort(key=lambda x:(bool(music.LIVE.search(str(x['name']))),x['fee'] not in (0,8,None) and not logged))
        save({**diag,'code':'matched','why':f'搜索正常：返回{len(songs)}条，匹配{len(candidates)}条；播放权限尚需逐曲确认'})
        return candidates
    music.ne_search=search
    original_search=music._search
    def source_search(src,*args,**kwargs):
        result=original_search(src,*args,**kwargs)
        if src=='netease' and not result[1]:
            diag=_last.get() or {}
            if diag.get('why'):raise RuntimeError(diag['why'])
        return result
    music._search=source_search
    original_test=music.selftest
    def selftest(*args,**kwargs):
        before=_last.get();result=original_test(*args,**kwargs);diag=_last.get()
        if diag is not before and diag and isinstance(result.get('netease'),dict):
            result['netease'].update(found=diag.get('raw_count',0),matched=diag.get('matched_count',0),search_ok=diag.get('search_ok'),search_code=diag.get('code'))
        return result
    music.selftest=selftest
    original_status=music.sources_status
    def status():
        result=original_status();diag=latest()
        if 'netease' in result and diag:
            old=result['netease'].get('why','')
            result['netease']['why']=(old+'；' if old else '')+'最近一次'+diag.get('why','')
        return result
    music.sources_status=status
