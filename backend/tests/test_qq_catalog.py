import asyncio
from io import BytesIO
import json
import hmac

from fastapi.testclient import TestClient
import httpx
from PIL import Image
from pydantic import ValidationError
import pytest

from backend.app.qq_bot import BotStore, QQSettings, create_app, group_query
from backend.app.qq_catalog import CatalogReplies, parse_query

IMAGE_ID = '9e1d8693-7754-41e8-8f31-1d6f3e056801'
MODEL_ID = '273b8b2a-2188-4493-a08d-bf5197ee7012'


def settings(tmp_path, **values):
    return QQSettings(account='12345678', allowed_groups='111', onebot_token='o' * 40,
                      catalog_token='c' * 40, state_path=str(tmp_path / 'qq.sqlite3'),
                      log_dir=str(tmp_path / 'logs'), **values)


def event(**values):
    data = {'post_type': 'message', 'message_type': 'group', 'self_id': 12345678,
            'group_id': 111, 'user_id': 222, 'message_id': 333,
            'message': [{'type': 'at', 'data': {'qq': '12345678'}}, {'type': 'text', 'data': {'text': '宝可梦 皮卡丘'}}]}
    return {**data, **values}


def signed_event(data=None, *, raw=None):
    body = raw if raw is not None else json.dumps(data or event(), ensure_ascii=False, separators=(',', ':')).encode()
    return {'content': body, 'headers': {'Content-Type': 'application/json', 'X-Signature': 'sha1=' + hmac.new(b'o' * 40, body, 'sha1').hexdigest()}}


@pytest.mark.parametrize('text,expected', [
    ('多美卡 Mark X', ('tomica', 'Mark X', 'info')),
    ('帮我找一下 tomica 丰田', ('tomica', '丰田', 'info')),
    ('宝可梦 皮卡丘的种族值', ('pokemon', '皮卡丘', 'stats')),
    ('皮卡丘能使用的招式学习器', ('pokemon', '皮卡丘', 'machine')),
    ('高达 飞翼', ('gunpla', '飞翼', 'info')),
    ('Pikachu', (None, 'Pikachu', 'info')),
])
def test_query_grammar(text, expected):
    assert parse_query(text) == expected


@pytest.mark.parametrize('change', [
    {'post_type': 'notice'}, {'message_type': 'private'}, {'self_id': 87654321},
    {'user_id': 12345678}, {'group_id': 999}, {'anonymous': {'name': 'anonymous'}},
    {'message': [{'type': 'at', 'data': {'qq': 'all'}}]},
    {'message': [{'type': 'text', 'data': {'text': '[CQ:at,qq=12345678] 搜索'}}]},
    {'message': [{'type': 'at', 'data': {'qq': '12345678'}}, {'type': 'text', 'data': {'text': 'x' * 201}}]},
])
def test_ignores_unaddressed_or_unapproved_events(tmp_path, change):
    assert group_query(event(**change), settings(tmp_path)) is None


def test_event_scope_and_unconfigured_account(tmp_path):
    config = settings(tmp_path)
    assert group_query(event(), config) == ('111', '222', '333', '宝可梦 皮卡丘')
    assert group_query(event(), config.model_copy(update={'account': ''})) is None
    assert group_query(event(), config.model_copy(update={'allowed_groups': ''})) is None
    assert group_query(event(group_id=999), config.model_copy(update={'allowed_groups': '*'}))


def test_persistent_dedup_and_context_isolation(tmp_path):
    path = tmp_path / 'state.sqlite3'
    store = BotStore(path)
    assert store.claim('111', '222', '333', now=10)
    assert not store.claim('111', '222', '334', now=11)  # Flood control.
    assert not BotStore(path).claim('111', '999', '333', now=15)  # Repeated event after restart.
    assert store.claim('999', '222', '333', now=15)
    store.save_context('111', '222', {'items': [1]})
    assert BotStore(path).context('111', '222')['items'] == [1]
    assert store.context('111', '999') is None and store.context('999', '222') is None
    with store.connect() as db:
        db.execute('UPDATE context SET expires=0')
    assert store.context('111', '222') is None


def catalog_response(request, calls):
    calls.append(request)
    assert request.headers['X-Catalog-Service'] == 'c' * 40
    path = request.url.path
    if path == '/api/pokemon':
        return httpx.Response(200, json={'items': [{'dex': 25, 'name_zh': '皮卡丘'}], 'total': 1})
    if path == '/api/pokemon/25':
        return httpx.Response(200, json={'dex': 25, 'name_zh': '皮卡丘', 'types': ['电'],
            'preview_image_url': '/api/reference-images/' + IMAGE_ID,
            'extra': {'base_stats': [{'label': '通常形态', 'stats': [{'name': 'HP', 'value': 35}], 'total': 35}]}})
    if path == '/api/gunpla/filters':
        return httpx.Response(200, json={'brands': [{'id': '2', 'name': 'RG'}]})
    if path == '/api/gunpla':
        return httpx.Response(200, json={'items': [{'id': '99', 'name': 'RG 飞翼高达'}], 'total': 1})
    if path == '/api/gunpla/products/99':
        return httpx.Response(200, json={'id': '99', 'name': 'RG 飞翼高达', 'price_cny_text': '¥100', 'price_jpy_text': '2000日元', 'release_text': '2026年11月', 'cover': '/api/reference-images/' + IMAGE_ID, 'gallery': [1, 2], 'detail_images': [3]})
    if path == '/api/tomica':
        return httpx.Response(200, json={'items': [{'id': MODEL_ID, 'name_original': 'TOYOTA MARK X'}], 'total': 1})
    if path == '/api/tomica/' + MODEL_ID:
        return httpx.Response(200, json={'id': MODEL_ID, 'name_original': 'TOYOTA MARK X', 'brand': 'Toyota', 'release_year': 2010, 'variants': [], 'preview_image_url': '/api/reference-images/' + IMAGE_ID})
    if path.startswith('/api/reference-images/'):
        image = BytesIO(); Image.new('RGB', (10, 10), 'red').save(image, 'PNG')
        return httpx.Response(200, content=image.getvalue(), headers={'content-type': 'image/png'})
    raise AssertionError(path)


@pytest.mark.parametrize('query,category,name,detail', [
    ('多美卡 Mark X', '多美卡', 'TOYOTA MARK X', '#tomica/' + MODEL_ID),
    ('宝可梦 皮卡丘的种族值', '宝可梦', '皮卡丘', '#pokemon/25'),
    ('高达 RG 飞翼', '高达', 'RG 飞翼高达', '#product/99'),
])
def test_catalog_name_image_detail_and_private_credentials(tmp_path, query, category, name, detail):
    calls = []
    async def run():
        async with httpx.AsyncClient(base_url='http://127.0.0.1:8092', headers={'X-Catalog-Service': 'c' * 40}, transport=httpx.MockTransport(lambda request: catalog_response(request, calls))) as client:
            replies = CatalogReplies(client, BotStore(tmp_path / 'state'), 'https://example.test')
            segments = await replies.reply('111', '222', query)
            text = segments[0]['data']['text']
            assert category in text and name in text and detail in text
            assert segments[1]['data']['file'].startswith('base64://')
            assert 'source' not in text and '/api/reference-images' not in text and 'c' * 40 not in json.dumps(segments)
            assert await replies.image('https://evil.example/api/reference-images/' + IMAGE_ID, 'tomica') is None
    asyncio.run(run())
    paths = [str(r.url) for r in calls]
    if category == '高达':
        query_request = next(r for r in calls if r.url.path == '/api/gunpla')
        assert query_request.url.params['grade'] == '2' and query_request.url.params['q'] == '飞翼'
        assert any('/display?width=480' in path for path in paths)


def test_candidates_pagination_and_selection_are_per_user(tmp_path):
    def handler(request):
        if request.url.path == '/api/tomica':
            return httpx.Response(200, json={'items': [{'id': str(i), 'name_original': f'车{i}'} for i in range(12)], 'total': 12})
        if request.url.path == '/api/tomica/5':
            return httpx.Response(200, json={'name_original': '车5'})
        raise AssertionError(str(request.url))
    async def run():
        async with httpx.AsyncClient(base_url='http://127.0.0.1:8092', transport=httpx.MockTransport(handler)) as client:
            replies = CatalogReplies(client, BotStore(tmp_path / 'state'), 'https://example.test')
            result = await replies.reply('111', '222', '多美卡 丰田')
            assert '1. [多美卡] 车0' in result[0]['data']['text']
            result = await replies.reply('111', '222', '下一页')
            assert '6. [多美卡] 车5' in result[0]['data']['text']
            assert '车5' in (await replies.reply('111', '222', '6'))[0]['data']['text']
            assert '过期' in (await replies.reply('999', '222', '下一页'))[0]['data']['text']
    asyncio.run(run())


def test_no_results_and_bad_images_do_not_invent_facts(tmp_path):
    async def run():
        async with httpx.AsyncClient(base_url='http://127.0.0.1:8092', transport=httpx.MockTransport(lambda r: httpx.Response(200, json={'items': [], 'total': 0}))) as client:
            replies = CatalogReplies(client, BotStore(tmp_path / 'state'), 'https://example.test')
            assert '没有找到' in (await replies.reply('111', '222', '宝可梦 没有这个名字'))[0]['data']['text']
            assert await replies.image('/api/reference-images/' + IMAGE_ID, 'pokemon') is None
    asyncio.run(run())


def test_pokemon_extra_preserves_version_and_form():
    extra = {'matchups': [{'label': '通常', 'types': [{'name': '地面', 'multiplier': '2'}]}], 'movesets': [{'kind': 'machine', 'method': '招式学习器', 'game': '朱紫', 'form': '通常形态', 'moves': [{'name': '十万伏特'}]}]}
    assert '地面 ×2' in CatalogReplies.pokemon_extra(extra, 'matchups')[0]
    assert '朱紫 · 通常形态 · 招式学习器：十万伏特' == CatalogReplies.pokemon_extra(extra, 'machine')[0]
    assert '暂无' in CatalogReplies.pokemon_extra(extra, 'learn')[0]


@pytest.mark.parametrize('values', [{'catalog_api': 'https://evil.example'}, {'account_api': 'http://127.0.0.1@evil.example'}, {'onebot_token': 'short'}, {'account': 'x'}, {'allowed_groups': 'abc'}])
def test_configuration_fails_closed(tmp_path, values):
    config = settings(tmp_path).model_dump()
    config.update(values)
    with pytest.raises(ValidationError):
        QQSettings(**config)


def test_http_callback_auth_dedup_and_acknowledged_delivery(tmp_path):
    config = settings(tmp_path)
    calls, sent = [], []
    def account(request):
        assert request.headers['authorization'] == 'Bearer ' + 'o' * 40
        assert 'x-catalog-service' not in request.headers
        if request.url.path == '/get_login_info':
            return httpx.Response(200, json={'status': 'ok', 'data': {'user_id': 12345678}})
        payload = json.loads(request.content)
        assert request.url.path == '/send_group_msg' and payload['group_id'] == 111
        sent.append(payload)
        return httpx.Response(200, json={'status': 'ok', 'retcode': 0, 'data': {'message_id': 444}})
    app = create_app(config, catalog_transport=httpx.MockTransport(lambda r: catalog_response(r, calls)), account_transport=httpx.MockTransport(account))
    with TestClient(app, client=('127.0.0.1', 10000)) as client:
        assert client.post('/onebot/events', json=event()).status_code == 403
        assert client.post('/onebot/events', **signed_event(raw=b'x' * 65537)).status_code == 413
        assert client.post('/onebot/events', **signed_event(raw=b'invalid')).status_code == 400
        tampered = signed_event(); tampered['content'] += b' '
        assert client.post('/onebot/events', **tampered).status_code == 403
        assert client.post('/onebot/events', **signed_event()).json()['accepted']
        assert not client.post('/onebot/events', **signed_event()).json()['accepted']
        client.portal.call(app.state.queue.join)
        assert len(sent) == 1
        assert client.get('/health/ready').status_code == 200
        assert client.get('/health/live').json()['last_reply_at']
    logs = (tmp_path / 'logs/collection.jsonl').read_text(encoding='utf-8')
    assert 'qq_catalog_reply_sent' in logs and 'o' * 40 not in logs and 'c' * 40 not in logs


def test_error_reply_is_not_marked_delivered_without_qq_ack(tmp_path):
    config = settings(tmp_path)
    app = create_app(config, catalog_transport=httpx.MockTransport(lambda r: httpx.Response(503)), account_transport=httpx.MockTransport(lambda r: httpx.Response(200, json={'status': 'failed', 'retcode': 1})))
    with TestClient(app, client=('127.0.0.1', 10000)) as client:
        client.post('/onebot/events', **signed_event())
        client.portal.call(app.state.queue.join)
        status = client.get('/health/live').json()
        assert status['last_reply_at'] is None and status['last_error'] == 'ValueError'
        assert client.get('/health/ready').status_code == 503
