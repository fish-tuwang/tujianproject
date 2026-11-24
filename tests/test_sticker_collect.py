import io
import json
import sys
from types import SimpleNamespace
import pytest
from PIL import Image
from qqbot.fatfish_extensions import common,sticker_collect


@pytest.fixture
def store(tmp_path,monkeypatch):
    data=tmp_path/'data';data.mkdir();monkeypatch.setattr(common,'DATA',data)
    thumb=data/'preview.jpg'
    Image.new('RGB',(12,12),'blue').save(thumb)
    fake=SimpleNamespace(configure=lambda *a,**k:None,reload=lambda:None,load=lambda:{'items':{'abc':{'fix':'睡觉'}}},thumb_path=lambda sid:thumb)
    monkeypatch.setitem(sys.modules,'stickerdict',fake)
    return data,thumb


def test_collect_requires_explicit_preview_then_is_selectable_and_idempotent(store):
    data,thumb=store
    assert not sticker_collect.collect('abc')['ok']
    assert not (data.parent/'stickers/index.json').exists()
    result=sticker_collect.collect('abc',preview=True)
    assert result['ok'] and result['preview']
    index=json.loads((data.parent/'stickers/index.json').read_text())
    entry=index['stickers'][result['name']]
    assert (data.parent/'stickers'/entry['file']).read_bytes()==thumb.read_bytes()
    assert sticker_collect.collect('abc',preview=True)['already']
    assert not sticker_collect.collect('../not-an-entry',preview=True)['ok']


def test_original_animation_is_preserved(store):
    import hashlib
    data,_=store
    folder=data/'sticker_originals';folder.mkdir()
    out=io.BytesIO()
    Image.new('RGB',(12,12),'red').save(out,format='GIF',save_all=True,append_images=[Image.new('RGB',(12,12),'green')],duration=100)
    raw=out.getvalue();(folder/(hashlib.sha256(b'abc').hexdigest()+'.bin')).write_bytes(raw)
    r=sticker_collect.collect('abc')
    assert r['ok'] and not r['preview']
    entry=json.loads((data.parent/'stickers/index.json').read_text())['stickers'][r['name']]
    saved=data.parent/'stickers'/entry['file']
    assert saved.read_bytes()==raw and Image.open(saved).n_frames==2


def test_collect_ui_does_not_conflate_description_save_and_image_import():
    html='<button data-save>保存</button>\n    if (e.target.closest("[data-save]")) {'
    transformed=sticker_collect.enhance(html)
    assert '收为表情包' in transformed and 'collect:true' in transformed
    assert '保存解释' in transformed and 'preview:true' in transformed
