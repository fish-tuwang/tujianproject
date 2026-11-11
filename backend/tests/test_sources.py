from pathlib import Path
import httpx
import pytest
from backend.app.sources.http import SourceHttpClient, normalize_url
from backend.app.sources.tomica import TomicaAdapter, normalize_brand
from backend.app.sources.pokemon import PokemonAdapter, LIST_URL

FIXTURES = Path(__file__).parent / 'fixtures'


def test_transient_source_disconnect_retries_with_rate_limit():
    calls = []
    sleeps = []
    def respond(request):
        calls.append(request.url.path)
        if request.url.path == '/robots.txt':
            return httpx.Response(200, text='User-agent: *\nAllow: /')
        if len(calls) == 2:
            raise httpx.RemoteProtocolError('Server disconnected without sending a response.')
        return httpx.Response(200, content=b'<html>source</html>')
    client = SourceHttpClient('pokemon', transport=httpx.MockTransport(respond), sleep=sleeps.append)
    try:
        result = client.fetch('https://wiki.52poke.com/zh-hans/蘑蘑菇')
        assert not result.error and result.body == b'<html>source</html>'
        assert len(calls) == 3 and len(sleeps) >= 2
        assert 2 in sleeps
    finally:
        client.close()


def parsed(name, species):
    return PokemonAdapter().parse('https://wiki.52poke.com/zh-hans/' + species, (FIXTURES / name).read_bytes())


def test_tomica_actual_number_table():
    page = TomicaAdapter().parse('http://tomica.minibird.jp/t-tomica/number/tba000.html', (FIXTURES / 'tomica-number.html').read_bytes())
    models = {c.source_key: c for c in page.candidates if c.kind == 'tomica_model'}
    assert models['001-1'].fields['release_year'] == 1970
    assert models['001-1'].fields['release_month'] == 9
    assert models['001-1'].fields['brand'] == 'Nissan'
    assert models['001-2'].fields['release_year'] == 1974
    assert models['001-1'].fields['scale'] == '1/60'
    versions = [c for c in page.candidates if c.kind == 'tomica_variant' and c.evidence['model_key'] == '001-1']
    assert versions and all(c.fields.get('release_year') is None for c in versions)
    assert all('wanted' not in c.evidence['image_url'].lower() for c in versions)
    assert '001-1:1-1-1' not in [c.source_key for c in versions]  # 原图位置为 WANTED


def test_supplement_is_not_manufacturer():
    page = TomicaAdapter().parse('http://tomica.minibird.jp/t-tomica/special/tto%20Honda.html', (FIXTURES / 'tomica-special.html').read_bytes())
    # Supplement editions are now explicitly in scope; manufacturer still comes
    # from the referenced car, rather than from the ordering company's page title.
    model = next(c for c in page.candidates if c.kind == 'tomica_model')
    assert model.fields['brand'] == 'Honda'
    assert model.source_key.startswith('edition:')
    assert any('/number/' in url for url in page.discovered_urls)
    assert normalize_brand('トイザらス') is None


def test_actual_duplicate_anchor_keeps_explicit_title_identity():
    for filename, expected in [('tba006.html', {'006-5', '006-13'}), ('tba036.html', {'039-8A', '039-8B'}), ('tba121.html', {'121-1', '122-1'})]:
        page = TomicaAdapter().parse('http://tomica.minibird.jp/t-tomica/number/' + filename, (FIXTURES / filename).read_bytes())
        models = [c for c in page.candidates if c.kind == 'tomica_model']
        assert expected <= {c.source_key for c in models}
        assert len({c.source_key for c in models}) == len(models)
    assert normalize_brand('ニッサン シルビア') == 'Nissan'


def test_actual_long_and_special_headers_without_anchors():
    for filename, expected in [('tbal-1.html', {'L-9', 'L-18'}), ('tbas01.html', {'SP-1', 'SP-10'})]:
        page=TomicaAdapter().parse('http://tomica.minibird.jp/t-tomica/number/'+filename,(FIXTURES/filename).read_bytes())
        models=[c for c in page.candidates if c.kind=='tomica_model']
        assert expected<={c.source_key for c in models}
        assert len({c.source_key for c in models})==len(models)
        assert all(c.fields['name_original'] for c in models)


def test_legacy_special_fullwidth_codes_are_not_merged_into_new_sp_numbers():
    for filename, key in [('tbas1.html','S1'),('tbas11.html','S11'),('tbas31.html','S31')]:
        page=TomicaAdapter().parse('http://tomica.minibird.jp/t-tomica/number/'+filename,(FIXTURES/filename).read_bytes())
        model=next(c for c in page.candidates if c.kind=='tomica_model' and c.source_key==key)
        assert model.fields['series']=='Tomica Special Legacy'


def test_tomica_filename_encoding_matches_legacy_server():
    url='http://tomica.minibird.jp/t-tomica/special/tto%20V%E3%83%BBfa-ren.html'
    assert normalize_url(url,url,'tomica').endswith('tto%20V%81Efa-ren.html')
    assert normalize_url(url,url,'tomica')==normalize_url(url,'tto V・fa-ren.html','tomica')


def test_pokemon_list_actual():
    page = PokemonAdapter().parse(LIST_URL, (FIXTURES / 'pokemon-list.html').read_bytes())
    assert page.candidates[0].fields['dex'] == 1
    assert page.candidates[0].fields['name_zh'] == '妙蛙种子'
    assert page.candidates[0].fields['name_en'] == 'Bulbasaur'
    assert len({c.fields['dex'] for c in page.candidates}) == len(page.candidates)


def test_real_regional_form_uses_its_own_artwork():
    page = parsed('pokemon-forms.html', '六尾')
    forms = {c.fields['form_key']: c for c in page.candidates if c.kind == 'pokemon_form'}
    assert '/037Vulpix.png/' in forms['default'].evidence['image_url']
    assert '/037Vulpix-Alola.png/' in forms['alola'].evidence['image_url']
    assert '_Dream' not in forms['alola'].evidence['image_url']


@pytest.mark.parametrize('dex,expected', [(778, ['778Mimikyu_Busted_Dream.png']), (842, ['841Flapple-Gigantamax.png']), (845, ['845Cramorant-Gulping_Form_Dream.png', '845Cramorant-Gorging_Form_Dream.png'])])
def test_form_artwork_follows_source_artwork_slot_even_for_shared_files(dex, expected):
    body = (FIXTURES / f'pokemon-{dex}.html').read_bytes()
    page = PokemonAdapter().parse('https://wiki.52poke.com/wiki/species', body)
    urls = [c.evidence.get('image_url', '') for c in page.candidates if c.kind == 'pokemon_form']
    assert all(any(name in url for url in urls) for name in expected)


def test_actual_infobox_and_excluded_navigation():
    page = parsed('pokemon-detail.html', '妙蛙种子')
    pokemon = page.candidates[0].fields
    assert pokemon['dex'] == 1 and pokemon['types'] == ['草', '毒']
    assert pokemon['height_m'] == 0.7 and pokemon['weight_kg'] == 6.9
    assert pokemon['abilities'] == ['茂盛', '叶绿素']
    assert pokemon['name_ja'] == 'フシギダネ'


def test_actual_regional_form():
    page = parsed('pokemon-forms.html', '六尾')
    form = next(c for c in page.candidates if c.kind == 'pokemon_form' and c.fields['form_key'] == 'alola')
    assert form.fields['types'] == ['冰']
    assert page.candidates[0].fields['types'] == ['火']


def test_actual_branch_evolution_conditions():
    page = parsed('pokemon-evolution.html', '伊布')
    edges = {c.fields['to_dex']: c.fields for c in page.candidates if c.kind == 'evolution' and c.fields['from_dex'] == 133}
    assert set(edges) == {134, 135, 136, 196, 197, 470, 471, 700}
    assert edges[134]['condition'] == '使用 水之石'
    assert edges[135]['condition'] == '使用 雷之石'
    assert '白天' in edges[196]['condition'] and '夜晚' in edges[197]['condition']
    assert '叶之石' in edges[470]['condition']


@pytest.mark.parametrize('url', ['http://127.0.0.1/a', 'http://tomica.minibird.jp/other/a.html', 'https://wiki.52poke.com/index.php?a=1', 'https://user:pass@wiki.52poke.com/wiki/a', 'https://wiki.52poke.com/wiki/%2e%2e/test'])
def test_url_boundary(url):
    with pytest.raises(ValueError):
        normalize_url(url, url, 'pokemon' if '52poke' in url else 'tomica')


def http_client(handler):
    ticks = [0.0]
    waits = []
    def sleep(seconds):
        waits.append(seconds)
        ticks[0] += seconds
    client = SourceHttpClient('pokemon', transport=httpx.MockTransport(handler), clock=lambda: ticks[0], sleep=sleep)
    return client, waits


def test_cache_robots_and_rate():
    calls = []
    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, text='User-agent: *\nDisallow: /wiki/blocked') if request.url.path == '/robots.txt' else httpx.Response(304)
    client, waits = http_client(handler)
    assert client.fetch('https://wiki.52poke.com/wiki/a', etag='v1').not_modified
    assert client.fetch('https://wiki.52poke.com/wiki/blocked').error == 'ROBOTS_DISALLOWED'
    assert len(calls) == 2 and waits == [2]
    client.close()


def test_retry_limit_and_redirect_rejection():
    count = [0]
    def handler(request):
        if request.url.path == '/robots.txt':
            return httpx.Response(404)
        count[0] += 1
        return httpx.Response(429, headers={'Retry-After': '3'})
    client, waits = http_client(handler)
    result = client.fetch('https://wiki.52poke.com/wiki/a')
    assert result.error == 'HTTP_429' and count[0] == 3
    client.close()
    client, _ = http_client(lambda r: httpx.Response(404) if r.url.path == '/robots.txt' else httpx.Response(302, headers={'location': 'http://127.0.0.1/'}))
    assert 'boundary' in client.fetch('https://wiki.52poke.com/wiki/a').error
    client.close()
