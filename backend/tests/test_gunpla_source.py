from pathlib import Path
from types import SimpleNamespace
import json
import pytest

from backend.app.sources.gunpla import BASE, EXCLUDED_BRANDS, is_model_product, parse_date, parse_home, parse_listing, parse_product
from backend.app.sources.http import normalize_url
from scripts.sync_gunpla import GunplaCrawler, exclusive

FIXTURES = Path(__file__).parent / 'fixtures/gunpla'


def fixture(name):
    return (FIXTURES / (name + '.html')).read_bytes()


def product(key='3425'):
    listing = next(p for p in parse_listing(BASE + '/index/index/brand/cate/15', fixture('eg'))['items'] if p['official_id'] == key)
    return parse_product(BASE + '/index/index/detail/id/' + key, fixture('detail-' + key), listing)


def test_full_official_model_brands_and_works_exclude_accessory_directories():
    rows = parse_home(fixture('home'))
    brands = [r for r in rows if r['kind'] == 'brand']
    assert len(brands) == 17
    assert {r['source_key'] for r in brands}.isdisjoint(EXCLUDED_BRANDS)
    assert {'148', '12', '13', '16', '17', '18', '68', '102', '109'} <= {r['source_key'] for r in brands}
    assert len([r for r in rows if r['kind'] == 'series']) == 39
    events = [r for r in rows if r['kind'] == 'event']
    assert events and len({r['source_key'] for r in events}) == len(events)
    assert {'线上', '线下'} <= {r['data']['channel'] for r in events}


def test_official_sale_categories_and_all_intermediate_pages():
    base = parse_listing(BASE + '/index/index/brand/cate/15?tag=3', fixture('eg-base'))
    online = parse_listing(BASE + '/index/index/brand/cate/6?tag=2', fixture('hg-online'))
    assert base['items'] and all(r['sale_types'] == ['3'] for r in base['items'])
    assert online['pages'] == 5 and all(r['sale_types'] == ['2'] for r in online['items'])
    assert parse_listing(BASE + '/index/index/brand/cate/15', fixture('eg'))['pages'] == 2


@pytest.mark.parametrize('key,count,cny,jpy', [('3425', 4, None, '1,760日元(含税)'), ('3027', 10, '60元', '1,100日元(含税)')])
def test_real_products_keep_every_original_in_order_and_separate_cover(key, count, cny, jpy):
    entry = product(key)
    data = entry['data']
    assert entry['source_key'] == key and '飞翼高达' in entry['name']
    assert len(data['gallery_urls']) == count == len(set(data['gallery_urls']))
    assert data['cover_url'] not in data['gallery_urls']
    assert data['price_cny_text'] == cny and data['price_jpy_text'] == jpy
    assert data['scale'] == '1/144' and data['series_ids'] == ['28']
    assert data['release_precision'] == 'month' and '日' not in data['release_text']
    assert not data['detail_image_urls']
    assert all('水贴' not in url for url in data['gallery_urls'])


@pytest.mark.parametrize('name,allowed', [
    ('HG 1/144 独立武器套组', False), ('SDCS 骨架(白色)', False),
    ('PG LED组件', False), ('MG 1/100 高达扩张零件包', False),
    ('PG 1/60 能天使高达用LED发光组件', False), ('SDCS 骨架[灰色]', False),
    ('HGBC 1/144 K9猎犬背包', False), ('HGBC 1/144 万能推进器', False),
    ('HG BUILD CUSTOM 1/144 创制推进器', False), ('HG BUILD CUSTOM 1/144 惊异推进器', False),
    ('HGBD:R 1/144 海王星八型组件', False), ('HGBD:R 1/144 土星六型武器', False),
    ('HGBD:R 1/144 Injustice Weapons', False), ('SD高达 CROSS SILHOUETTE 外形提升零件（白色）', False),
    ('MGSD 自由高达', True), ('BB战士 武者高达', True),
    ('HG 高达(附带武器套组)', True), ('HG 高达+武器套组', True),
    ('高达汇战 扩展补充包 04 [EX04]', True),
    ('RG 1/144 机动战士高达 最终射击 吉翁号特效零件套装', True),
    ('RG 1/144 空中霸王[强袭高达炮装/剑装背包]', True),
    ('HG 1/144 无限正义高达&推进组件（暂定）', True),
])
def test_only_standalone_accessories_are_excluded(name, allowed):
    entry = {'name': name, 'data': {'brand_ids': ['6'], 'series_ids': ['29']}}
    assert is_model_product(entry, {'29'})[0] is allowed


def test_non_gundam_work_and_accessory_brand_are_not_published():
    entry = {'name': 'HG unrelated model', 'data': {'brand_ids': ['6'], 'series_ids': ['outside']}}
    assert is_model_product(entry, {'29'}) == (False, 'non_gundam_work')
    entry['data']['brand_ids'] = ['69']
    assert is_model_product(entry, {'29'}) == (False, 'accessory_brand')


def test_verified_retail_correction_is_limited_to_its_exact_official_identity():
    # Synthetic boundary only; the real product galleries are checked separately.
    listing = {'brand_ids': ['6'], 'sale_types': [], 'cover_url': 'https://staticcdn.bandaihobbysite.cn/www/assets/synthetic.jpg'}
    body = '<main><h1>HGCC 1/144 ∀高达</h1></main>'
    value = parse_product(BASE + '/index/index/detail/id/993', body, listing)
    assert value['data']['sale_types'] == ['1']
    assert value['data']['classification_evidence'].startswith('https://prtimes.jp/')
    assert not parse_product(BASE + '/index/index/detail/id/994', body, listing)['data']['sale_types']
    assert not parse_product(BASE + '/index/index/detail/id/993', body.replace('∀高达', '其他高达'), listing)['data']['sale_types']


@pytest.mark.parametrize('key', ['2993', '2863', '3245', '233', '2990', '2920', '976'])
def test_verified_accessory_identity_is_excluded_despite_a_compatibility_model_name(key):
    entry = {'kind': 'product', 'source_key': key, 'name': 'Gundam compatible accessory', 'data': {'official_id': key, 'brand_ids': ['6'], 'series_ids': ['29']}}
    assert is_model_product(entry, {'29'}) == (False, 'standalone_accessory')


@pytest.mark.parametrize('suffix', ['/index/index/detail/id/3425?tag=3', '/admin', '/gunpla#anything', '/index/index/brand/cate/6?page=0', '/index/index/brand/cate/6?tag=5', '/index/index/brand/cate/6?tag=1&tag=2', '/index/index/brand/cate/6?page=1&evil=1'])
def test_gunpla_http_boundary_rejects_other_paths_and_unregistered_queries(suffix):
    with pytest.raises(ValueError):
        normalize_url(BASE, suffix, 'gunpla')
    with pytest.raises(ValueError):
        normalize_url(BASE, 'https://bandaihobbysite.cn.evil.test/gunpla', 'gunpla')


def test_canonical_query_and_precise_dates():
    assert normalize_url(BASE, '/index/index/brand/cate/6?tag=2&page=5', 'gunpla').endswith('?page=5&tag=2')
    assert parse_date('2026年2月7日') == ('2026-02-07', 'day')
    assert parse_date('2026年8月') == ('2026-08-01', 'month')
    assert parse_date('2026年2月31日') == (None, None)


def test_checkpoint_survives_not_modified_and_limit_never_claims_completeness(tmp_path):
    now, calls = [1000], []
    class Client:
        def fetch(self, url, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(error=None, body=b'<main>original</main>' if len(calls) == 1 else b'', etag='same', last_modified=None)
    crawler = GunplaCrawler(tmp_path, mode='full', client=Client(), clock=lambda: now[0])
    url = BASE + '/gunpla'
    assert crawler.read(url) == b'<main>original</main>'
    assert crawler.read(url) == b'<main>original</main>' and len(calls) == 1
    now[0] += 1
    assert crawler.read(url, force=True) == b'<main>original</main>' and calls[-1]['etag'] == 'same'
    crawler.checkpoint(True)
    assert not json.loads(crawler.output.read_text(encoding='utf-8'))['coverage']['complete']


def test_second_synchronizer_cannot_enter_the_same_source_directory(tmp_path):
    with exclusive(tmp_path):
        with pytest.raises(OSError):
            with exclusive(tmp_path):
                pass


def test_rechecking_accessory_does_not_keep_an_older_model_checkpoint(tmp_path, monkeypatch):
    from scripts import sync_gunpla
    entry = {'kind': 'product', 'source_key': '2150', 'name': 'PG 1/60 能天使高达用LED发光组件', 'data': {'brand_ids': ['14'], 'series_ids': ['29']}}
    crawler = GunplaCrawler(tmp_path, client=SimpleNamespace())
    crawler.products['2150'] = entry
    monkeypatch.setattr(crawler, 'read', lambda *a, **k: b'')
    monkeypatch.setattr(sync_gunpla, 'parse_home', lambda body: [{'kind': 'brand', 'source_key': '14', 'name': 'PG'}, {'kind': 'series', 'source_key': '29', 'name': 'Gundam'}])
    def listing(url):
        crawler.listings['2150'] = {'official_id': '2150', 'name': entry['name'], 'brand_ids': ['14'], 'source_url': BASE + '/index/index/detail/id/2150'}
        return 1
    monkeypatch.setattr(crawler, 'collect_listing', listing)
    result = crawler.run()
    assert not [r for r in result['entries'] if r['kind'] == 'product']
    assert result['coverage']['excluded'] == [{'id': '2150', 'name': entry['name'], 'reason': 'standalone_accessory'}]
