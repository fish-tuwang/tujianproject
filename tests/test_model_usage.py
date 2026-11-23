import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import httpx
import pytest
from qqbot.fatfish_extensions import usage,common
from qqbot.fatfish_extensions.usage_ui import enhance_usage_ui


@pytest.fixture(autouse=True)
def isolated(tmp_path,monkeypatch):
    monkeypatch.setattr(common,'DATA',tmp_path/'data');common.DATA.mkdir()
    monkeypatch.setattr(usage,'_DIRECTORY',tmp_path)
    (tmp_path/'config.json').write_text(json.dumps({'llm':{'provider':'qwen','qwen':{'model':'qwen-plus','base_url':'https://dashscope.aliyuncs.com/compatible-mode/v1'}}}))
    usage._pending.set(None)


def u(inp=1000,out=100,cached=200,reason=0):
    return {'prompt_tokens':inp,'completion_tokens':out,'prompt_tokens_details':{'cached_tokens':cached},'completion_tokens_details':{'reasoning_tokens':reason}}


def test_qwen_cache_counts_and_official_decimal_tiers():
    q=usage.quote('qwen-plus','dashscope.aliyuncs.com',u())
    assert q['cost']==pytest.approx((800*.8+200*.16+100*2)/1e6)
    assert usage.quote('qwen-plus','dashscope.aliyuncs.com',u(128000))['input_per_million']==.8
    assert usage.quote('qwen-plus','dashscope.aliyuncs.com',u(128001))['input_per_million']==2.4
    assert usage.quote('qwen-plus','dashscope.aliyuncs.com',u(256001))['output_per_million']==48
    assert usage.quote('qwen-plus','dashscope.aliyuncs.com',u(reason=10))['output_per_million']==8
    assert usage.quote('qwen-plus','dashscope.aliyuncs.com',u(),thinking=True)['thinking']


def test_unknown_model_region_and_missing_usage_are_not_falsely_free():
    for model,host,data in [('new-qwen','dashscope.aliyuncs.com',u()),('qwen-plus','other.example',u()),('qwen-plus','dashscope.aliyuncs.com',None)]:
        assert usage.quote(model,host,data) is None
        usage.record(data,model,meta={'model':model,'host':host})
    s=usage.snapshot()
    assert sum(r['unpriced_calls'] for r in s['models'])==3
    assert sum(r['cost_cny'] for r in s['models'])==0


def test_actual_models_remain_separate_and_historical_records_preserved():
    common.write(common.DATA/'stats.json',{'days':{common.day():{'llm_calls':10,'tok_miss':1234}}})
    for model in ['qwen-plus','qwen-plus-2025-12-01']:
        usage.record(u(),model,'聊天',{'model':model,'host':'dashscope.aliyuncs.com','requested_model':'qwen-plus'})
    usage.record(u(),'qwen-plus','统计验收',{'model':'qwen-plus','host':'dashscope.aliyuncs.com'},legacy_counted=False)
    s=usage.snapshot()
    assert len(s['models'])==2 and sum(r['calls'] for r in s['models'])==3
    assert s['legacy_unattributed_calls']==8
    assert common.read(common.DATA/'stats.json',{})['days'][common.day()]['tok_miss']==1234
    assert 'api_key' not in json.dumps(s)


def test_transport_captures_actual_response_and_translates_qwen_thinking(monkeypatch):
    original=httpx.AsyncClient.post;monkeypatch.setattr(httpx.AsyncClient,'post',original)
    usage.install_transport()
    bodies=[]
    def respond(request):
        body=json.loads(request.content);bodies.append(body)
        return httpx.Response(200,json={'model':'qwen-plus-2025-12-01','usage':u(),'choices':[{'message':{'content':'OK'}}]})
    async def call():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            await client.post('https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions',json={'model':'qwen-plus','thinking':{'type':'disabled'}})
        meta=usage._pending.get()
        assert meta['model']=='qwen-plus-2025-12-01' and not meta['thinking']
        usage.record(u(),'qwen-plus','测试',meta)
    asyncio.run(call())
    assert bodies[0]['enable_thinking'] is False and 'thinking' not in bodies[0]
    assert usage.snapshot()['models'][0]['model']=='qwen-plus-2025-12-01'


def test_upstream_stats_receive_normalized_usage_without_deepseek_spend(monkeypatch,tmp_path):
    calls=[];spent=[]
    module=SimpleNamespace(llm=lambda *a,**k:calls.append((a,k)),peak_now=lambda now=None:True,_prices={'usd_cny':7.1},_spend=spent.append)
    monkeypatch.setitem(sys.modules,'stats',module)
    original=httpx.AsyncClient.post;monkeypatch.setattr(httpx.AsyncClient,'post',original)
    usage.install(tmp_path)
    usage._pending.set({'usage':u(),'model':'qwen-plus','host':'dashscope.aliyuncs.com'})
    module.llm(u(),'qwen-plus','聊天')
    assert calls[0][0][0]['prompt_cache_hit_tokens']==200 and calls[0][1]['budget'] is False
    assert module.peak_now() is False
    assert spent[0]==pytest.approx(usage.quote('qwen-plus','dashscope.aliyuncs.com',u())['cost']/7.1)


def test_ui_replaces_deepseek_views_before_native_render():
    html='VIEWS.stats = async main => {\n old();\n};\nconst CUR = {};\nVIEWS.usage = async main => {\n old();\n};'
    changed=enhance_usage_ui(html)
    assert 'old();' not in changed and 'async function atlasModelUsage' in changed
    assert '实际 API 返回' in changed and '百炼账单' in changed
