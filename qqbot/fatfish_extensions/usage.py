"""Provider-aware usage from API responses; catalogue estimates are not invoices."""
import contextvars
import json
import time
from pathlib import Path
from urllib.parse import urlsplit
from . import common

PRICE_SOURCE='https://help.aliyun.com/zh/model-studio/model-pricing'
CACHE_SOURCE='https://help.aliyun.com/en/model-studio/context-cache'
PRICE_DATE='2026-11-23'
_pending=contextvars.ContextVar('atlas_usage_response',default=None)
_DIRECTORY=None


def config():
    c=common.read(_DIRECTORY/'config.json',{}) if _DIRECTORY else {}
    return c


def active_model():
    llm=config().get('llm',{});provider=llm.get('provider','unknown');spec=llm.get(provider,{})
    return {'provider':provider,'model':spec.get('model','unknown')}


def number(v):
    try:return max(0,int(v or 0))
    except (ValueError,TypeError,OverflowError):return 0


def tokens(usage):
    u=usage if isinstance(usage,dict) else {};details=u.get('prompt_tokens_details') or {}
    if not isinstance(details,dict):details={}
    total=number(u.get('prompt_tokens',u.get('input_tokens',0)))
    hit=number(details.get('cached_tokens',u.get('prompt_cache_hit_tokens',0)))
    hit=min(hit,total)
    out=number(u.get('completion_tokens',u.get('output_tokens',0)))
    reasoning=min(out,number((u.get('completion_tokens_details') or {}).get('reasoning_tokens')))
    return {'input':total,'cached':hit,'output':out,'reasoning':reasoning}


def quote(model,host,usage,thinking=False):
    """Verified Beijing qwen-plus catalogue. Unsupported combinations stay unknown."""
    t=tokens(usage)
    if isinstance(usage,dict) and (number(usage.get('cache_creation_input_tokens')) or number((usage.get('prompt_tokens_details') or {}).get('cache_creation_tokens'))):return None
    aliases={'qwen-plus','qwen-plus-latest','qwen-plus-2025-12-01','qwen-plus-2025-07-14','qwen-plus-2025-04-28'}
    if host!='dashscope.aliyuncs.com' or model not in aliases or not isinstance(usage,dict) or not usage or 'prompt_tokens' not in usage or 'completion_tokens' not in usage:return None
    n=t['input'];thinking=bool(thinking or t['reasoning'])
    if model in {'qwen-plus-2025-07-14','qwen-plus-2025-04-28'}:limit,inp,out=1000000,.8,8 if thinking else 2
    elif n<=128000:limit,inp,out=128000,.8,8 if thinking else 2
    elif n<=256000:limit,inp,out=256000,2.4,24 if thinking else 20
    elif n<=1000000:limit,inp,out=1000000,4.8,64 if thinking else 48
    else:return None
    return {'currency':'CNY','input_per_million':inp,'cached_per_million':round(inp*.2,8),
            'output_per_million':out,'tier_max_input':limit,'thinking':thinking,
            'cost':((n-t['cached'])*inp+t['cached']*inp*.2+t['output']*out)/1e6,
            'source':PRICE_SOURCE,'cache_source':CACHE_SOURCE,'verified_at':PRICE_DATE}


def install_transport():
    import httpx
    original=httpx.AsyncClient.post
    if getattr(original,'_atlas_usage',False):return
    async def post(self,url,*args,**kwargs):
        body=kwargs.get('json') or {}
        if (urlsplit(str(url)).hostname=='dashscope.aliyuncs.com' and isinstance(body,dict)
            and body.get('model') in {'qwen-plus','qwen-plus-latest','qwen-plus-2025-12-01','qwen-plus-2025-07-14','qwen-plus-2025-04-28'}
            and isinstance(body.get('thinking'),dict)):
            body=dict(body);thinking=body.pop('thinking');body.setdefault('enable_thinking',thinking.get('type')=='enabled')
            kwargs={**kwargs,'json':body}
        response=await original(self,url,*args,**kwargs)
        if urlsplit(str(url)).path.endswith('/chat/completions') and response.status_code<400:
            try:
                d=response.json();body=kwargs.get('json') or {};u=d.get('usage')
                think=body.get('enable_thinking',False) or (body.get('thinking') or {}).get('type')=='enabled'
                message=((d.get('choices') or [{}])[0].get('message') or {})
                _pending.set({'usage':u,'model':d.get('model') or body.get('model') or 'unknown',
                              'requested_model':body.get('model') or 'unknown','host':urlsplit(str(url)).hostname,
                              'thinking':bool(think or message.get('reasoning_content'))})
            except (ValueError,TypeError,AttributeError,IndexError):_pending.set(None)
        return response
    post._atlas_usage=True
    httpx.AsyncClient.post=post


def record(usage,model,tag='',meta=None,now=None,legacy_counted=True):
    now=time.time() if now is None else now
    # When no transport metadata exists, do not guess which endpoint/model was used.
    meta=meta or {'model':model or 'unknown','requested_model':model or 'unknown','host':None,'thinking':False}
    actual=str(meta.get('model') or model or 'unknown')[:100]
    host=meta.get('host');provider='qwen' if host=='dashscope.aliyuncs.com' and actual.startswith('qwen') else 'unknown'
    t=tokens(usage);q=quote(actual,host,usage,meta.get('thinking',False))
    key='|'.join([provider,actual,'think' if q and q['thinking'] else 'normal',str(q['tier_max_input']) if q else 'unpriced',str((q['input_per_million'],q['cached_per_million'],q['output_per_million'],q['verified_at'])) if q else ''])
    def change(d):
        d.setdefault('version',1);d.setdefault('started_at',now)
        day=d.setdefault('days',{}).setdefault(common.day(now),{})
        row=day.setdefault(key,{'provider':provider,'model':actual,'requested_model':str(meta.get('requested_model',''))[:100],
                              'calls':0,'legacy_counted_calls':0,'input':0,'cached':0,'output':0,'reasoning':0,'cost_cny':0.,'unpriced_calls':0,'by':{},'price':{k:v for k,v in q.items() if k!='cost'} if q else None})
        row['calls']+=1
        row['legacy_counted_calls']=row.get('legacy_counted_calls',0)+int(legacy_counted)
        for k,v in t.items():row[k]+=v
        if q:row['cost_cny']+=q['cost']
        else:row['unpriced_calls']+=1
        feature=row['by'].setdefault(str(tag or '其他')[:32],{'calls':0,'input':0,'cached':0,'output':0,'cost_cny':0.,'unpriced_calls':0})
        feature['calls']+=1
        for k in ['input','cached','output']:feature[k]+=t[k]
        if q:feature['cost_cny']+=q['cost']
        else:feature['unpriced_calls']+=1
        # Bound retention; do not store prompts, images, recipient identifiers or API keys.
        for date in sorted(d['days'])[:-90]:del d['days'][date]
        return q
    common.edit('model-usage.json',change)
    return q


def snapshot(days=30):
    days=max(1,min(90,int(days)))
    d=common.read(common.DATA/'model-usage.json',{})
    cutoff=common.day(time.time()-(days-1)*86400)
    models={};daily=[]
    for date,rows in sorted(d.get('days',{}).items()):
        if date<cutoff:continue
        item={'day':date,'calls':0,'input':0,'cached':0,'output':0,'cost_cny':0.,'unpriced_calls':0}
        for key,row in rows.items():
            agg=models.setdefault(key,{**{k:row.get(k) for k in ['provider','model','requested_model','price']},**{k:0 for k in ['calls','legacy_counted_calls','input','cached','output','reasoning','cost_cny','unpriced_calls']},'by':{}})
            for k in ['calls','legacy_counted_calls','input','cached','output','reasoning','cost_cny','unpriced_calls']:agg[k]+=row.get(k,0)
            for k in item:
                if k!='day':item[k]+=row.get(k,0)
            for tag,values in row.get('by',{}).items():
                target=agg['by'].setdefault(tag,{})
                for k,v in values.items():target[k]=target.get(k,0)+v
        daily.append(item)
    # Historical aggregate counters lack model/mode/tier and cannot be relabelled.
    legacy=common.read(common.DATA/'stats.json',{}).get('days',{})
    calls=sum(v.get('llm_calls',0) for k,v in legacy.items() if k>=cutoff)
    tracked=sum(v.get('legacy_counted_calls',0) for v in models.values())
    return {'ok':True,'active':active_model(),'started_at':d.get('started_at'),'models':list(models.values()),'daily':daily,
            'legacy_unattributed_calls':max(0,calls-tracked),'price_source':PRICE_SOURCE,'cache_source':CACHE_SOURCE,
            'note':'Token取自API返回；费用按调用时官方单价估算，优惠、赠送额度和最终扣费以百炼账单为准。旧记录缺少模型/计费档位，不冒充精确费用。'}


def install(bot_directory):
    global _DIRECTORY
    _DIRECTORY=Path(bot_directory)
    import importlib
    stats=importlib.import_module('stats')
    if getattr(stats,'_atlas_usage',False):return
    original=stats.llm;peak=stats.peak_now
    def llm(usage,model='',tag='',budget=True,free_reason=False):
        meta=_pending.get();_pending.set(None)
        if meta and meta.get('usage')!=usage:meta=None
        t=tokens(usage);normalized={**(usage or {}),'prompt_cache_hit_tokens':t['cached'],
                                  'prompt_cache_miss_tokens':t['input']-t['cached']}
        original(normalized,model,tag,budget=False,free_reason=free_reason)
        try:q=record(usage,model,tag,meta)
        except (OSError,ValueError,TypeError):
            q=None;print('[用量统计] 保存失败，本次模型回复不会因此重试',flush=True)
        if budget and q:stats._spend(q['cost']/max(.01,stats._prices.get('usd_cny',7.1)))
    stats.llm=llm
    stats.peak_now=lambda now=None:False if active_model()['provider']=='qwen' else peak(now)
    stats._atlas_usage=True
    install_transport()


def install_panel(panel):
    if getattr(panel,'_atlas_usage_panel',False):return
    panel._atlas_usage_panel=True
    original_balance=panel.deepseek_balance
    panel.deepseek_balance=lambda force=False:({'ok':False,'error':'当前使用千问，余额和实际扣费请到百炼账单核对'} if active_model()['provider']=='qwen' else original_balance(force))
    original_peak=panel.peak_view
    panel.peak_view=lambda:({'enabled':False,'now':False,'text':'千问不适用DeepSeek峰谷计价'} if active_model()['provider']=='qwen' else original_peak())
    original_cost=panel.cost_of
    def base_cost(d,p):
        value=original_cost(d,p)
        # The upstream formula assumes DeepSeek and cannot price provider-less history.
        value['total']=max(0,value['total']-value['deepseek']-value['search'])
        value.update(deepseek=0.,llm=0.,search=0.,peak=0.,model_cost_incomplete=True)
        return value
    panel.cost_of=base_cost
    def amounts(days):
        snap=snapshot(days);by_day={d['day']:d['cost_cny']/max(.01,panel.prices()['usd_cny']) for d in snap['daily']}
        return snap,by_day
    original_stats=panel.stats_view
    def stats_view(days=14):
        result=original_stats(days);snap,costs=amounts(days)
        for row in result['days']:
            row['cost']['llm']=costs.get(row['day'],0.);row['cost']['total']+=row['cost']['llm']
        value=sum(costs.values());result['total']['cost']['llm']=value;result['total']['cost']['total']+=value
        result['model_usage']=snap
        return result
    panel.stats_view=stats_view
    original_overview=panel.overview
    def overview():
        result=original_overview();snap,costs=amounts(1);value=sum(costs.values())
        result['today']['cost'].update(llm=value,total=value)
        result['model_usage']={'active':snap['active'],'tracked_since':snap['started_at'],'legacy_unattributed_calls':snap['legacy_unattributed_calls']}
        return result
    panel.overview=overview
