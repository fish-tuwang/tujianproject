import pytest
from qqbot.fatfish_extensions.idle_links import idle_without_links


@pytest.mark.parametrize('url',[
 'https://b23.tv/BV114s26qEYf',r'https\://b23.tv/BV114s26qEYf',
 'b23.tv/abc','www.example.com/x','https://music.163.com/#/song?id=123',
 'example.cn/abc','ftp://example.com/file',
])
def test_idle_text_removes_links(url):
 assert idle_without_links('看看 '+url+' 好玩')=='看看  好玩'


def test_idle_removes_cards_and_empty_content_but_keeps_images():
 card={'type':'json','data':{'data':'https://example.com'}}
 image={'type':'image','data':{'file':'https://example.com/image.png'}}
 assert idle_without_links([card])==[]
 assert idle_without_links([card,image])==[image]
 assert idle_without_links([{'type':'text','data':{'text':'https://b23.tv/a'}}])==[]


def test_markdown_and_cq_links():
 assert idle_without_links('[歌曲](https://music.163.com/song?id=1)')=='歌曲'
 assert idle_without_links('[CQ:share,url=https://example.com,title=test]')==''


def test_original_message_is_not_mutated():
 message=[{'type':'text','data':{'text':'https://music.163.com/song?id=1'}}]
 assert idle_without_links(message)==[]
 assert message[0]['data']['text']=='https://music.163.com/song?id=1'


def test_mentioned_search_reply_keeps_song_link(tmp_path):
 import hashlib,hmac,json,threading
 import httpx
 from fastapi.testclient import TestClient
 from qqbot.qq_bot import QQSettings,create_app
 url='https://music.163.com/song?id=123'
 sent=[];done=threading.Event()
 def model(request):
  return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'text':url,'sticker_id':'','image_prompt':''})}}]})
 def account(request):
  if request.url.path=='/get_login_info':return httpx.Response(200,json={'status':'ok','data':{'user_id':949494401}})
  sent.append(json.loads(request.content));done.set()
  return httpx.Response(200,json={'status':'ok','retcode':0,'data':{'message_id':123}})
 settings=QQSettings(account='949494401',onebot_token='x'*40,llm_key='y'*40,allowed_groups='10',state_path=str(tmp_path/'bot.sqlite'),log_dir=str(tmp_path/'logs'))
 app=create_app(settings,llm_transport=httpx.MockTransport(model),account_transport=httpx.MockTransport(account))
 event={'post_type':'message','message_type':'group','self_id':949494401,'user_id':12345,'group_id':10,'message_id':'abc','message':[{'type':'at','data':{'qq':'949494401'}},{'type':'text','data':{'text':'share a song link'}}]}
 body=json.dumps(event).encode();signature='sha1='+hmac.new(b'x'*40,body,hashlib.sha1).hexdigest()
 with TestClient(app,client=('127.0.0.1',1234)) as client:
  assert client.post('/onebot/events',content=body,headers={'x-signature':signature}).json()['accepted']
  assert done.wait(3)
 assert any(url in s.get('data',{}).get('text','') for s in sent[0]['message'])
