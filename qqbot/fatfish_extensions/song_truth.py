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
        text+='\n# 点歌分享模式（最高优先级）\n用户点歌时只按已设置找歌来源查找并分享对应平台的歌曲或视频页面链接。不要承诺唱歌、开麦、换声、剪辑、语音或音频附件；不要写歌词。需要执行点歌时仍使用 [[唱:歌名 - 歌手]] 标记，程序会只发送来源链接；不要把标记说成演唱。查不到就说明未找到，不编链接或进度。\n'
        return text
    sing.block=block;sing._truth_installed=True
