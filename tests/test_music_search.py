import json
import re
import sys
from types import SimpleNamespace
import pytest
from qqbot.fatfish_extensions import common,music_search


@pytest.fixture
def platform(tmp_path,monkeypatch):
 monkeypatch.setattr(common,'DATA',tmp_path)
 music_search._last.set(None)
 m=SimpleNamespace(ne_abroad=lambda:False,_NE={},ABROAD_HOLD=21600,LIVE=re.compile('Live'),
  _login_cookies=lambda src:{'MUSIC_U':'private-login-secret'},_ne_headers=lambda ck:{'Cookie':'MUSIC_U='+ck['MUSIC_U']},
  _ok_name=lambda name,title,req:name==title,_artist_ok=lambda names,artist:not artist or artist in names,
  sources_status=lambda:{'netease':{'ok':True,'enabled':True,'why':''}})
 def source(src,title,artist,*args,**kwargs):
  result=m.ne_search(title,artist,log=lambda *a:None);return result,result
 m._search=source
 def selftest(*args,**kwargs):
  try:raw,cands=m._search('netease','晴天','周杰伦');return {'netease':{'ok':bool(cands),'found':len(raw)}}
  except RuntimeError as e:return {'netease':{'ok':False,'found':0,'why':str(e)}}
 m.selftest=selftest
 monkeypatch.setitem(sys.modules,'music',m)
 def response(payload,status=200):
  def request(method,url,**kwargs):
   assert kwargs['headers']['Cookie']=='MUSIC_U=private-login-secret'
   return SimpleNamespace(status_code=status,json=lambda:payload)
  m._http=request
 m.reply=response;m.ne_search=lambda *a,**k:[];m._http=lambda *a,**k:None;music_search.install();return m


def test_real_search_results_are_not_misreported_as_empty(platform):
 platform.reply({'code':200,'result':{'songs':[{'id':1,'name':'晴天','artists':[{'name':'Jay'}]}]}})
 with pytest.raises(RuntimeError,match='返回1条，未匹配指定原唱'):
  platform._search('netease','晴天','周杰伦')
 d=music_search.latest();assert d['raw_count']==1 and d['artist_rejected']==1 and d['search_ok'] and d['login_used']
 assert d['code']=='no_matching_original'
 assert 'private-login-secret' not in json.dumps(d)
 assert platform.sources_status()['netease']['ok'] is True


def test_selftest_reports_raw_count_and_specific_filter_failure(platform):
 platform.reply({'code':200,'result':{'songs':[{'id':1,'name':'晴天','artists':[{'name':'翻唱歌手'}]}]}})
 result=platform.selftest()['netease']
 assert result['found']==1 and result['matched']==0 and result['search_ok']
 assert '什么都没搜到' not in result['why'] and result['ok'] is False


@pytest.mark.parametrize('payload,status,code',[
 ({},503,'http_error'),({'code':301},200,'api_rejected'),
 ({'code':200,'result':'opaque'},200,'invalid_result'),
 ({'code':200,'result':{'songs':[]}},200,'empty_results'),
 ({'code':200,'abroad':True,'result':'opaque'},200,'abroad_response'),
])
def test_search_failures_are_distinct_without_resetting_login(platform,payload,status,code):
 platform.reply(payload,status);assert not platform.ne_search('晴天','周杰伦',log=lambda *a:None)
 assert music_search.latest()['code']==code
 assert platform._login_cookies('netease')['MUSIC_U']=='private-login-secret'


def test_known_original_still_matches_and_keeps_playback_separate(platform):
 platform.reply({'code':200,'result':{'songs':[{'id':1,'name':'平凡之路','artists':[{'name':'朴树'}],'duration':270000,'fee':1}]}})
 candidates=platform.ne_search('平凡之路','朴树')
 assert len(candidates)==1 and candidates[0]['dur']==270
 assert music_search.latest()['code']=='matched' and '播放权限尚需逐曲确认' in music_search.latest()['why']
