import hashlib
import json
import sqlite3
from PIL import Image
from qqbot import fatfish_mac as adapter
from qqbot.qq_chat import fatfish_personality


def test_idle_prefers_sleep_and_never_repeats_decoded_picture(tmp_path, monkeypatch):
    monkeypatch.setattr(adapter, 'ROOT', tmp_path)
    folder = tmp_path / 'stickers'
    folder.mkdir()
    for name, color in [('sleep-a','red'),('sleep-copy','red'),('sleep-b','blue'),('other','green'),('disabled','yellow')]:
        Image.new('RGB', (3,3), color).save(folder / (name + '.png'))
    index = {name: {'file': name + '.png', 'text': 'DeepSleep' if name.startswith('sleep') else '', 'off': name == 'disabled'} for name in ['sleep-a','sleep-copy','sleep-b','other','disabled']}
    (folder / 'index.json').write_text(json.dumps({'stickers':index}))
    first = adapter.idle_sticker('1')
    assert first.stem.startswith('sleep-')
    adapter.rotate_images('1', {'message':[{'type':'image','data':{'file':str(first)}}]}, remember=True)
    second = adapter.idle_sticker('1')
    assert Image.open(second).tobytes() != Image.open(first).tobytes()
    assert second.stem.startswith('sleep-')
    for name in index:
        index[name]['off'] = True
    (folder / 'index.json').write_text(json.dumps({'stickers':index}))
    assert adapter.idle_sticker('1') is None


def test_profile_prohibits_keyword_echo_and_idle_text():
    text = fatfish_personality()
    assert '禁止抽取用户关键词加问号敷衍' in text
    assert '只随机发送一张现成表情包' in text
    assert '不附带任何文字' in text
