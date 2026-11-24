"""Capability-grounded music replies; conversion failure may deliver an audio file."""
from pathlib import Path


def audio_fallback(params, result):
    if result.get('retcode') == 0:return None
    message=str(result.get('message') or '')
    if 'ntsilk_s16le' not in message:return None
    records=[x for x in params.get('message',[]) if x.get('type')=='record']
    if len(records)!=1:return None
    return records[0].get('data',{}).get('file')


def install():
    import sing
    if getattr(sing,'_truth_installed',False):return
    original=sing.block
    def block(*args,**kwargs):
        text=original(*args,**kwargs)
        cfg=sing._cfg.get('cover') or {}
        key=Path(cfg.get('key_file') or '')
        configured=bool(cfg.get('enabled') and key.is_file() and cfg.get('url'))
        text+='\n# 音乐交付事实\n发出之前不得说已经唱完、已发送或已找到音源。网络原唱片段必须称为原唱音频，不得称为自己的演唱、即兴remix。语音失败可能改发音频文件，以实际发送结果为准。不要虚构声线加载、开麦或音源搜索进度。\n'
        if not configured:text+='当前没有配置有效换声服务；不得承诺使用鲸鱼声线或自己的声音。\n'
        return text
    sing.block=block;sing._truth_installed=True
