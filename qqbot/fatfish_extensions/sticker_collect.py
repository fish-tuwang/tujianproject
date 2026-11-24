"""Explicit owner collection, separate from editing recognition descriptions."""
import hashlib
import io
import json
from pathlib import Path

from . import common


def collect(sid, *, preview=False):
    import stickerdict
    from PIL import Image
    stickerdict.configure({}, data_dir=common.DATA)
    stickerdict.reload()
    if sid not in stickerdict.load()['items']:
        return {'ok':False, 'error':'词条不存在'}
    token = hashlib.sha256(sid.encode()).hexdigest()
    source = common.DATA / 'sticker_originals' / (token + '.bin')
    used_preview = not source.is_file()
    if used_preview:
        if not preview:
            return {'ok':False, 'error':'原图未保留；可明确选择保存静态预览图，或等群友重新发送原图。'}
        source = stickerdict.thumb_path(sid)
    if not source.is_file():
        return {'ok':False,'error':'没有可用图片，请让群友重新发送这张表情包。'}
    raw = source.read_bytes()
    if len(raw) > 5*1024*1024:
        return {'ok':False,'error':'图片超过5MB'}
    try:
        with Image.open(io.BytesIO(raw)) as im:
            ext = {'PNG':'.png','JPEG':'.jpg','GIF':'.gif','WEBP':'.webp'}.get(im.format)
            im.verify()
        if not ext:raise ValueError()
    except (OSError, ValueError):
        return {'ok':False,'error':'图片损坏或格式不支持，未收录'}
    folder = common.DATA.parent / 'stickers'
    folder.mkdir(parents=True, exist_ok=True)
    key = 'collected-' + token[:20]
    index = folder / 'index.json'
    with common.locked(index):
        value = common.read(index, {'stickers':{}})
        old = value.setdefault('stickers',{}).get(key)
        if old and (folder / old.get('file','')).is_file():
            return {'ok':True,'name':key,'preview':bool(old.get('preview')), 'already':True}
        filename = key + ext
        tmp = folder / (filename + '.tmp')
        tmp.write_bytes(raw);tmp.replace(folder / filename)
        entry = stickerdict.load()['items'][sid]
        value['stickers'][key] = {'file':filename,'emo':'搞怪','scene':str(entry.get('fix') or (entry.get('deep') or {}).get('usage') or '群聊表情')[:300], 'note':'所有者手动收录', 'preview':used_preview}
        common.write(index,value)
        saved = common.read(index,{})['stickers'][key]
        assert (folder / saved['file']).is_file()
    return {'ok':True,'name':key,'preview':used_preview}


def install():
    import stickerdict
    if getattr(stickerdict, '_original_cache_installed', False):return
    original = stickerdict._thumb
    def thumb(sid, data):
        # Keep actual bytes (including animation); a JPEG thumbnail is not the original.
        if data and len(data) <= 5*1024*1024:
            folder = common.DATA / 'sticker_originals'
            folder.mkdir(parents=True,exist_ok=True)
            path = folder / (hashlib.sha256(str(sid).encode()).hexdigest() + '.bin')
            tmp = path.with_suffix('.tmp');tmp.write_bytes(data);tmp.replace(path)
        return original(sid,data)
    stickerdict._thumb = thumb
    stickerdict._original_cache_installed = True


def enhance(html):
    html = html.replace('data-save>保存</button>', 'data-save>保存解释</button><button class="btn small" data-collect>收为表情包</button>')
    html = html.replace('    if (e.target.closest("[data-save]")) {', '''    if (e.target.closest("[data-collect]")) {
      const b = e.target.closest("[data-collect]"); b.disabled = true;
      try {
        let r = await api("/api/stickerdict_edit", {id:c.dataset.sid, collect:true});
        if (!r.ok && r.error && r.error.includes("原图未保留") && confirm(r.error + "\\n是否保存静态预览图？动画不会保留。")) {
          r = await api("/api/stickerdict_edit", {id:c.dataset.sid, collect:true, preview:true});
        }
        toast(r.ok ? (r.preview ? "已保存静态预览图，可在表情包页选择" : "已保存原图，可在表情包页选择") : (r.error || "未收录"), !r.ok);
        if (r.ok) b.textContent = "已收录";
      } finally { b.disabled = false; }
    } else if (e.target.closest("[data-save]")) {''')
    return html.replace('改动机器人 30 秒内生效', '保存解释只修改词条；点“收为表情包”才加入可发送图库。解释由机器人后台处理')
