"""Run real FatFish panel handlers against throwaway data and a fake QQ gateway.

Use the installed FatFish venv. No production config/data is copied, no QQ login
is started, and subprocess/network access is blocked before imports. Output is
safe JSON containing only check names and outcomes.
"""
import argparse
import asyncio
import base64
import io
import json
from pathlib import Path
from contextlib import redirect_stdout
import shutil
import socket
import subprocess
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))


def run(upstream):
    from PIL import Image
    from qqbot import fatfish_mac as adapter
    checks = []
    class Unsupported(Exception):
        pass
    def check(name, fn):
        try:
            fn()
            checks.append({'check': name, 'status': 'passed'})
        except Unsupported as error:
            checks.append({'check': name, 'status': 'unsupported', 'reason': str(error)})
        except Exception as error:
            checks.append({'check': name, 'status': 'failed', 'category': type(error).__name__})
    def require(value):
        assert value
    def blocked(*args, **kwargs):
        raise RuntimeError('sandbox_external_io_blocked')
    with tempfile.TemporaryDirectory(prefix='fatfish-panel-sandbox-') as directory:
        root = Path(directory) / 'Application Support' / '鲸鱼'
        botdir = root / 'current' / 'bot'
        botdir.mkdir(parents=True)
        # Copy public source files only. Never follow private config/data links.
        for pattern in ('*.py', '*.html'):
            for path in upstream.glob(pattern):
                if not path.is_symlink():
                    shutil.copyfile(path, botdir / path.name)
        (botdir / 'data').mkdir()
        (botdir / 'config.json').write_text(json.dumps({
            'bot_qq': '10000', 'owner_qq': '10001', 'persona_file': 'persona.md',
            'behavior': {'group_reply_prob': .1}, 'panel': {'token': 'sandbox-only'},
        }))
        (botdir / 'persona.md').write_text('沙箱测试人设。' * 20)
        stickers = botdir / 'stickers'; stickers.mkdir()
        entries = {}
        for n, color in [('测试 困 #1+100%25', 'red'), ('测试 困 #2', 'blue')]:
            Image.new('RGB', (8, 8), color).save(stickers / (n + '.png'))
            entries[n] = {'file': n + '.png', 'emo': '困', 'scene': '沙箱'}
        (stickers / 'index.json').write_text(json.dumps({'stickers': entries}))
        (root / 'stickers').symlink_to(stickers, target_is_directory=True)
        adapter.ROOT = root
        socket.socket.connect = blocked
        socket.create_connection = blocked
        subprocess.Popen = blocked
        panel = adapter.load_module('panel')
        from qqbot.fatfish_extensions.panel import install
        install(panel)
        panel.BACKUP = root / 'backups'
        panel.bot_api = lambda *a, **k: {'ok': True, 'sandbox': True, 'data': []}
        panel.bot_busy = lambda: False
        panel.bot_procs = lambda: []
        panel.napcat_up = lambda: True
        panel.qq_running = lambda: True
        panel.ws_clients = lambda: False
        panel.qq_status = lambda: {'state': 'ok'}
        panel._bal.update(v={}, t=__import__('time').time())
        handler = object.__new__(panel.H)
        handler._host_ok = lambda: True
        handler._json = lambda value, code=200: (code, value)
        handler.headers = {'Host': '127.0.0.1:8765'}
        reads = ['config', 'people', 'tasks', 'shadow', 'followup', 'stickerdict',
                 'stickerlib', 'sources', 'memory', 'qzone', 'prank', 'fixup', 'life',
                 'memory/forget', 'favor', 'persons', 'stats', 'logs', 'persona',
                 'stickers', 'songs', 'local-core', 'music', 'overview', 'version']
        for name in reads:
            def read(name=name):
                handler.path = '/api/' + name
                code, body = handler.do_GET()
                require(code == 200 and isinstance(body, (dict, list)))
                if name == 'persons' and body.get('ok') is False and '没有人物卡' in str(body.get('error')):
                    raise Unsupported('upstream_personcard_module_not_published')
                require(not isinstance(body, dict) or body.get('ok') is not False)
            check('GET ' + name, read)
        writes = [
            ('persona', {'text': '只存在沙箱的新性格。' * 20}),
            ('config', {'changes': [{'path': 'behavior.group_reply_prob', 'value': .2}]}),
            ('control', {'kind': 'group', 'id': '123456', 'mode': 'normal'}),
            ('stickers/toggle', {'name': next(iter(entries)), 'off': True}),
            ('stickers/toggle', {'name': next(iter(entries)), 'off': False}),
            ('local-core', {'action': 'self_add', 'text': '沙箱笔记'}),
            ('local-core', {'action': 'reset_mood'}),
            ('prices', {'prices': {'cny_miss': 1.2}}),
        ]
        for name, body in writes:
            check('POST ' + name, lambda n=name, b=body: require(handler.route('/api/' + n, b).get('ok')))
        def song_cycle():
            wave = io.BytesIO()
            import wave as wav
            with wav.open(wave, 'wb') as w:
                w.setnchannels(1);w.setsampwidth(2);w.setframerate(8000);w.writeframes(b'\0' * 16000)
            result = handler.route('/api/songs/upload', {'filename': '测试.wav', 'data': base64.b64encode(wave.getvalue()).decode()})
            require(result.get('ok')); sid = result['song']['id']
            require(handler.route('/api/songs/save', {'id': sid, 'name': '改名歌曲'}).get('ok'))
            require(handler.route('/api/songs/delete', {'id': sid}).get('ok'))
        check('song upload/edit/delete', song_cycle)
        module = adapter.load_module('bot')
        sent = []
        async def gateway(data):
            require(data.get('operation') == 'action')
            sent.append(data)
            for segment in data['params'].get('message', []):
                if segment['type'] in {'image', 'record'}:
                    require(segment['data']['file'].startswith('base64://'))
                    require(bool(base64.b64decode(segment['data']['file'][9:])))
            return {'retcode': 0, 'status': 'ok', 'data': {'message_id': len(sent)}}
        adapter.call_gateway = gateway
        async def scenarios():
            fish = module.FatFish()
            for scene in ['group', 'private']:
                for text, sticker in [('沙箱文字', ''), ('', next(iter(entries))), ('混合消息', next(iter(entries)))]:
                    result = await fish._admin_send({'scene': scene, 'target': '123456', 'text': text, 'sticker': sticker, 'remember': False})
                    require(result['ok'] and not result.get('error'))
            path = next(stickers.glob('*.png'))
            require((await fish.call('send_group_msg', group_id=123456, message=[{'type': 'record', 'data': {'file': path.as_uri()}}]))['retcode'] == 0)
            before = len(sent)
            result = await fish.call('send_group_msg', group_id=123456, message=[{'type': 'image', 'data': {'file': (root / 'missing.png').as_uri()}}])
            require(result['retcode'] != 0 and len(sent) == before)
        module.main = scenarios
        check('real admin_send text/image/mixed group/private + voice + missing asset', lambda: asyncio.run(adapter.run_bot()))
        require(bool(sent))
        check('sandbox blocks Docker/processes', lambda: require(subprocess.Popen is blocked))
        check('sandbox blocks external sockets', lambda: require(socket.socket.connect is blocked))
    return {'sandbox': True, 'real_qq_messages': 0, 'checks': checks,
            'passed': sum(c['status'] == 'passed' for c in checks),
            'failed': sum(c['status'] == 'failed' for c in checks),
            'unsupported': sum(c['status'] == 'unsupported' for c in checks)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--upstream', type=Path, default=Path.home() / 'Library/Application Support/LittleAtlasQQ/fatfish/current/bot')
    args = parser.parse_args()
    with redirect_stdout(io.StringIO()):
        report = run(args.upstream)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(bool(report['failed']))
