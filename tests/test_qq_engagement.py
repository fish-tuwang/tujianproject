import asyncio,base64,json
from datetime import datetime
from io import BytesIO
from zoneinfo import ZoneInfo
import httpx
from PIL import Image,PngImagePlugin
from qqbot.engagement import batches,picture_key,segment_key,activity_target
from qqbot.qq_bot import BotStore,QQSettings
from qqbot.qq_images import ChatImages
from qqbot.qq_chat import ChatReplies


def ts(day=23,hour=10,minute=0):return datetime(2026,11,day,hour,minute,tzinfo=ZoneInfo('Asia/Shanghai')).timestamp()


def test_hourly_idle_without_mentions_survives_restart(tmp_path):
 s=BotStore(tmp_path/'bot.sqlite');s.note_activity('10',False,ts())
 assert not s.idle_candidates(ts(minute=59))
 assert s.idle_candidates(ts(hour=11))==['10']
 s.record_idle('10','bubble',ts(hour=11))
 s=BotStore(tmp_path/'bot.sqlite')
 assert not s.idle_candidates(ts(hour=11,minute=59))
 assert s.idle_candidates(ts(hour=12))==['10']
 s.record_idle('10','bubble',ts(hour=12))
 assert s.idle_candidates(ts(hour=13))==['10']
 s.record_idle('10','bubble',ts(hour=13))
 assert not s.idle_candidates(ts(hour=14))
 assert s.idle_candidates(ts(day=24))==['10']
 assert not s.idle_candidates(ts(day=24,hour=23))


def test_hourly_idle_mentions_recheck_and_independent_groups(tmp_path):
 s=BotStore(tmp_path/'bot.sqlite')
 for group in ['10','20']:s.note_activity(group,False,ts())
 s.note_activity('10',True,ts(hour=11))
 assert not s.idle_allowed('10',ts(hour=11,minute=1))
 assert s.idle_candidates(ts(hour=11,minute=1))==['20']


def make_images(tmp_path):
 entries=[]
 for i,color in enumerate(['red','blue','green','yellow']):
  p=tmp_path/f'{i}.png';Image.new('RGB',(8,8),color).save(p);entries.append({'id':str(i),'file':p.name,'description':'DeepSleep','tags':['睡觉'],'family':'sleep'})
 (tmp_path/'index.json').write_text(json.dumps({'entries':entries}));return ChatImages(None,None,root=tmp_path)


def test_same_caption_different_images_rotate_and_history_survives_restart(tmp_path):
 image_dir=tmp_path/'images';image_dir.mkdir();images=make_images(image_dir);path=tmp_path/'bot.sqlite';s=BotStore(path);keys=[]
 for _ in range(6):
  segment=asyncio.run(images.select({'sticker_id':'0'},excluded=s.recent_images('10')));key=segment_key(segment)
  assert key not in s.recent_images('10');s.record_image('10',key);keys.append(key);s=BotStore(path)
 assert len(set(keys[:4]))==4


def test_visual_key_ignores_png_caption_metadata():
 a=BytesIO();b=BytesIO();im=Image.new('RGB',(8,8),'red');meta=PngImagePlugin.PngInfo();meta.add_text('caption','different text');im.save(a,format='PNG');im.save(b,format='PNG',pnginfo=meta)
 assert a.getvalue()!=b.getvalue() and picture_key(a.getvalue())==picture_key(b.getvalue())


def test_image_only_reply_has_no_text_or_empty_quote_and_receives_real_time(tmp_path):
 image_dir=tmp_path/'images';image_dir.mkdir();images=make_images(image_dir);s=BotStore(tmp_path/'bot.sqlite');seen=[]
 class Model:
  async def post(self,path,json):
   seen.append(json);return httpx.Response(200,request=httpx.Request('POST','https://example.test'),json={'choices':[{'message':{'content':'{"reply_mode":"image_only","text":"","sticker_id":"0","image_prompt":""}'}}]})
 result=asyncio.run(ChatReplies(Model(),s,'test',images).reply('10','20','逗你一下'))
 assert [r['type'] for r in result]==['image']
 assert batches(result,'original-message')==[[result[0]]]
 assert '当前北京时间：' in seen[0]['messages'][0]['content']


def test_activity_includes_images_and_long_messages_but_not_self_or_other_groups():
 settings=QQSettings(account='949494401',onebot_token='x'*40,llm_key='y'*40,allowed_groups='10')
 event={'post_type':'message','message_type':'group','self_id':949494401,'user_id':12345,'group_id':10,'message':[{'type':'image','data':{}}]}
 assert activity_target(event,settings)==('10',False)
 assert activity_target({**event,'user_id':949494401},settings) is None
 assert activity_target({**event,'group_id':30},settings) is None


def test_onebot_worker_sends_only_the_image_and_records_it(tmp_path):
 import threading,hmac,hashlib
 from fastapi.testclient import TestClient
 from qqbot.qq_bot import create_app
 sent=[];done=threading.Event()
 def model(request):
  return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'reply_mode':'image_only','text':'','sticker_id':'sleep-pa-zhe-shui-jiao','image_prompt':''})}}]})
 def account(request):
  if request.url.path=='/get_login_info':return httpx.Response(200,json={'status':'ok','data':{'user_id':949494401}})
  sent.append(json.loads(request.content));done.set();return httpx.Response(200,json={'status':'ok','retcode':0,'data':{'message_id':123}})
 settings=QQSettings(account='949494401',onebot_token='x'*40,llm_key='y'*40,allowed_groups='10',state_path=str(tmp_path/'bot.sqlite'),log_dir=str(tmp_path/'logs'))
 app=create_app(settings,llm_transport=httpx.MockTransport(model),account_transport=httpx.MockTransport(account))
 event={'post_type':'message','message_type':'group','self_id':949494401,'user_id':12345,'group_id':10,'message_id':'abc','message':[{'type':'at','data':{'qq':'949494401'}},{'type':'text','data':{'text':'轻松接个梗'}}]};body=json.dumps(event).encode();signature='sha1='+hmac.new(b'x'*40,body,'sha1').hexdigest()
 with TestClient(app,client=('127.0.0.1',1234)) as client:
  assert client.post('/onebot/events',content=body,headers={'x-signature':signature}).json()['accepted']
  assert done.wait(3)
 assert len(sent)==1 and [s['type'] for s in sent[0]['message']]==['image']
 assert BotStore(tmp_path/'bot.sqlite').recent_images('10')


def test_small_family_can_rotate_without_repeating_last_picture(tmp_path):
 images=make_images(tmp_path)
 images.entries={k:v for k,v in images.entries.items() if k in ['0','1']}
 key0=images.keys['0'];key1=images.keys['1']
 result=asyncio.run(images.select({'sticker_id':'0'},excluded=[key0,key1]))
 assert segment_key(result)==key1


def test_mention_clock_ignores_chat_and_resets_at_exact_minute(tmp_path):
 s=BotStore(tmp_path/'bot.sqlite')
 s.note_activity('10',True,ts(hour=12,minute=23))
 s.note_activity('10',False,ts(hour=13,minute=22))
 assert not s.idle_allowed('10',ts(hour=13,minute=22))
 assert s.idle_allowed('10',ts(hour=13,minute=23))
 s.record_idle('10','bubble',ts(hour=13,minute=23))
 s.note_activity('10',False,ts(hour=14,minute=22))
 assert s.idle_allowed('10',ts(hour=14,minute=23))
 s.note_activity('10',True,ts(hour=14,minute=24))
 assert not s.idle_allowed('10',ts(hour=15,minute=23))
 assert BotStore(tmp_path/'bot.sqlite').idle_allowed('10',ts(hour=15,minute=24))


def test_first_seen_group_clock_does_not_follow_regular_chat(tmp_path):
 s=BotStore(tmp_path/'bot.sqlite')
 s.note_activity('10',False,ts(hour=12,minute=23))
 s.note_activity('10',False,ts(hour=13,minute=22))
 assert s.idle_allowed('10',ts(hour=13,minute=23))


def test_fatfish_continuing_bubble_only_cancelled_by_new_mention(tmp_path,monkeypatch):
 from fastapi import FastAPI
 from fastapi.testclient import TestClient
 from qqbot.fatfish_gateway import install_gateway
 s=BotStore(tmp_path/'bot.sqlite');now=ts(hour=13,minute=23)
 monkeypatch.setattr('qqbot.fatfish_gateway.time.time',lambda:now)
 settings=QQSettings(account='949494401',onebot_token='x'*40,llm_key='y'*40,allowed_groups='10',idle_enabled=True)
 app=FastAPI();install_gateway(app,settings,s,{})
 s.note_activity('10',True,now-3600)
 with TestClient(app,client=('127.0.0.1',1111)) as client:
  headers={'authorization':'Bearer '+'x'*40}
  body={'operation':'idle_check','group':'10'}
  result=client.post('/admin/fatfish',headers=headers,json=body).json()
  assert result['allowed']
  s.record_idle('10','bubble',now)
  s.note_activity('10',False,now)
  body.update(continuing=True,mention=result['mention'])
  assert client.post('/admin/fatfish',headers=headers,json=body).json()['allowed']
  s.note_activity('10',True,now)
  assert not client.post('/admin/fatfish',headers=headers,json=body).json()['allowed']
