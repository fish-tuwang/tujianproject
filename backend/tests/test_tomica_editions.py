from pathlib import Path

import pytest
from sqlalchemy import func, select

from backend.app.models import SourceIdentity, TomicaModel, TomicaVariant
from backend.app.repository import CatalogRepository
from backend.app.schemas import SourceCandidate, TomicaQuery
from backend.app.sources.tomica import BASE, TomicaAdapter

FIXTURES = Path(__file__).parent / 'fixtures'


def page(filename='tomica-dream.html', path='event/tiv%20dori-mutomica.html'):
    return TomicaAdapter().parse(BASE + path, (FIXTURES / filename).read_bytes())


def test_every_collection_menu_section_is_discovered():
    body = b'<a href="event/a.html">event</a><a href="character/b.html">character</a><a href="notsold/c.html">other</a><a href="gift/d.html">gift</a><a href="special/e.html">custom</a><a href="number/f.html">regular</a><a href="http://127.0.0.1/x.html">outside</a>'
    urls = TomicaAdapter().parse(BASE + 'menu.html', body).discovered_urls
    assert len(urls) == 6
    assert '/number/' in urls[0]
    assert all(url.startswith(BASE) for url in urls)


def test_actual_bread_thief_keeps_its_caption_and_exact_column_photo():
    parsed = page()
    models = [c for c in parsed.candidates if c.kind == 'tomica_model']
    assert len(models) == 482
    bread = next(c for c in models if c.evidence['caption'] == 'パンどろぼう')
    assert bread.fields['name_original'].startswith('パンどろぼう · 絵本コレクション')
    assert bread.evidence['image_urls'] == [BASE + 'event/IMG_9291.jpg']
    assert bread.fields['number'] == 'SP'
    assert bread.fields['release_year'] is None  # J2124 is a production mark.
    assert bread.fields['brand'] is None
    neighbor = next(c for c in models if c.evidence['caption'] == 'ねないこだれ')
    assert neighbor.evidence['image_urls'] == [BASE + 'event/IMG_9290.jpg']
    assert bread.source_key != neighbor.source_key
    for candidate in models:
        photos = [c.evidence['image_url'] for c in parsed.candidates if c.kind == 'tomica_variant' and c.evidence['model_key'] == candidate.source_key]
        assert photos == candidate.evidence['image_urls']


def test_actual_disney_gift_and_orderer_keep_independent_editions():
    disney = page('tomica-character.html', 'character/tca%20de.html')
    models = [c for c in disney.candidates if c.kind == 'tomica_model']
    assert len(models) == 924
    mickey = next(c for c in models if c.evidence['caption'] == 'D-01 ミッキーマウス')
    assert mickey.evidence['image_urls'] == [BASE + 'jpg/tomica collection2 763.jpg']
    assert mickey.fields['series'] == 'Tomica Character'
    gift = page('tomica-gift.html', 'gift/tgito%20tokyosky.html')
    trailer = next(c for c in gift.candidates if c.kind == 'tomica_model')
    assert trailer.fields['number'] == '137-1'
    assert trailer.fields['brand'] == 'Isuzu'
    assert '東京スカイツリー' in trailer.fields['name_original']


def test_same_original_across_directories_is_one_edition_and_idempotent(session):
    candidates = page('tomica-special.html', 'special/tto%20Honda.html').candidates
    repo = CatalogRepository(session)
    assert repo.publish_candidates(None, candidates, source='tomica') == 2
    original = session.scalar(select(TomicaModel))
    assert repo.publish_candidates(None, candidates, source='tomica') == 0
    repeated = [c.model_copy(deep=True) for c in candidates]
    for candidate in repeated:
        candidate.evidence['url'] = BASE + 'gift/repeated.html'
        candidate.fields['source_url'] = candidate.evidence['url']
        candidate.fields['name_original'] = '別の分類タイトル'
    assert repo.publish_candidates(None, repeated, source='tomica') == 0
    assert session.scalar(select(func.count()).select_from(TomicaModel)) == 1
    assert session.scalar(select(func.count()).select_from(TomicaVariant)) == 1
    assert session.scalar(select(func.count()).select_from(SourceIdentity)) == 2
    assert session.get(TomicaModel, original.id).source_url.endswith('tto%20Honda.html')


def test_same_page_encoding_correction_refreshes_evidence_and_keeps_edition_id(session):
    repo = CatalogRepository(session)
    old = SourceCandidate(kind='tomica_model', source_key='edition:unchanged-photo', fields={'number': 'SP', 'name_original': '繝代Φ'}, evidence={'url': BASE + 'special/utf8.html', 'caption': '繝代Φ'})
    repo.publish_candidates(None, [old], source='tomica')
    model_id = session.scalar(select(TomicaModel.id))
    fixed = old.model_copy(deep=True)
    fixed.fields['name_original'], fixed.evidence['caption'] = 'パンどろぼう', 'パンどろぼう'
    assert repo.publish_candidates(None, [fixed], source='tomica') == 1
    assert session.scalar(select(TomicaModel.id)) == model_id
    assert session.scalar(select(SourceIdentity)).evidence['caption'] == 'パンどろぼう'


def test_caption_repair_selects_mojibake_without_selecting_ordinary_japanese(session):
    import unicodedata
    from scripts.repair_tomica_editions import suspicious_names
    repo = CatalogRepository(session)
    broken = unicodedata.normalize('NFKC', '特注'.encode('utf-8').decode('cp932', errors='replace'))
    for key, name in [('good', '特注 トヨタ クラウン'), ('bad', broken + ' BMW')]:
        repo.publish_candidates(None, [SourceCandidate(kind='tomica_model', source_key=key, fields={'number': 'SP', 'name_original': name, 'source_url': BASE + key + '.html'})], source='tomica')
    assert list(session.scalars(select(TomicaModel.source_url).where(suspicious_names()))) == [BASE + 'bad.html']


def test_collaboration_names_are_searchable_without_changing_source_name(session):
    parsed = page()
    selected = [c for c in parsed.candidates if c.kind == 'tomica_model' and c.evidence['caption'] == 'パンどろぼう']
    repo = CatalogRepository(session)
    repo.publish_candidates(None, selected, source='tomica')
    for query in ['面包小偷', '麵包小偷', 'Bread Thief', 'PANDOROBOU', 'パンどろぼう']:
        result = repo.list_tomica(TomicaQuery(q=query, page=1))
        assert result['total'] == 1
        assert result['items'][0]['name_original'].startswith('パンどろぼう')
    assert repo.list_tomica(TomicaQuery(q='面包小偷', brand='Toyota', page=1))['total'] == 0


def test_number_search_does_not_match_an_internal_photo_fingerprint(session):
    repo = CatalogRepository(session)
    repo.publish_candidates(None, [
        SourceCandidate(kind='tomica_model', source_key='edition:abc114def', fields={'number': 'SP', 'name_original': 'パンどろぼう', 'source_locator': 'edition:abc114def'}),
        SourceCandidate(kind='tomica_model', source_key='114-1', fields={'number': '114', 'name_original': 'トラック', 'source_locator': '114-1'}),
    ], source='tomica')
    result = repo.list_tomica(TomicaQuery(q='114', page=1))
    assert result['total'] == 1
    assert result['items'][0]['number'] == '114'


def test_captionless_or_wanted_photos_do_not_create_invented_products():
    body = '<html><title>collection test</title><table><tr><td><img src="one.jpg"></td></tr></table><table><tr><td>bread</td></tr><tr><td>WANTED<img src="missing.jpg"></td></tr></table></html>'.encode('cp932')
    parsed = TomicaAdapter().parse(BASE + 'event/test.html', body)
    assert not parsed.candidates
    assert any(i.code == 'SUPPLEMENT_CAPTION_MISSING' for i in parsed.issues)


def test_shared_group_heading_does_not_invent_a_name_for_every_photo():
    body = '<title>collection 特注 ディズニー</title><table><tr><td colspan="3">裏板変更</td></tr><tr><td><img src="one.jpg"></td><td><img src="two.jpg"></td><td><img src="three.jpg"></td></tr></table>'.encode('cp932')
    parsed = TomicaAdapter().parse(BASE + 'special/test.html', body)
    assert not parsed.candidates
    assert sum(i.code == 'SUPPLEMENT_CAPTION_MISSING' for i in parsed.issues) == 3


def test_a_full_width_product_photo_can_use_its_own_shared_heading():
    body = '<table><tr><td colspan="2">パンどろぼう</td></tr><tr><td colspan="2"><img src="bread.jpg"></td></tr></table>'.encode('cp932')
    parsed = TomicaAdapter().parse(BASE + 'event/fullwidth.html', body)
    models = [c for c in parsed.candidates if c.kind == 'tomica_model']
    assert len(models) == 1 and models[0].evidence['caption'] == 'パンどろぼう'


@pytest.mark.parametrize('title', ['69-6 水族館トラック', 'No.1'])
def test_shared_heading_with_explicit_product_locator_keeps_its_editions(title):
    body = ('<table><tr><td colspan="2">' + title + '</td></tr><tr><td><img src="a.jpg"></td><td><img src="b.jpg"></td></tr></table>').encode('cp932')
    models = [c for c in TomicaAdapter().parse(BASE + 'event/numbered.html', body).candidates if c.kind == 'tomica_model']
    assert len(models) == 2
    assert all(c.evidence['caption'] == title for c in models)


def test_utf8_bytes_override_a_stale_shift_jis_declaration():
    body = '<meta charset="Shift_JIS"><title>collection 特注</title><table><tr><td>パンどろぼう</td><td>ねないこだれだ</td></tr><tr><td><img src="bread.jpg"></td><td><img src="ghost.jpg"></td></tr></table>'.encode('utf-8')
    parsed = TomicaAdapter().parse(BASE + 'event/utf8.html', body)
    models = [c for c in parsed.candidates if c.kind == 'tomica_model']
    assert [c.evidence['caption'] for c in models] == ['パンどろぼう', 'ねないこだれだ']
    assert all('�' not in c.fields['name_original'] for c in models)


def test_actual_utf8_custom_page_has_readable_names_and_no_guessed_group_only_cars():
    parsed = page('tomica-utf8.html', 'special/tto%202jikakouhin.html')
    models = [c for c in parsed.candidates if c.kind == 'tomica_model']
    assert len(models) == 1794
    assert models[0].fields['name_original'].startswith('クラッシックカーin小金井')
    assert not any('�' in c.fields['name_original'] for c in models)


@pytest.mark.parametrize('filename,path,expected', [('tomica-euc-extended.html', 'special/tto%20ebomi.html', 'エボリューション'), ('tomica-euc.html', 'special/tto%20higasinihonkousokudouro.html', '東日本高速道路')])
def test_actual_euc_pages_keep_readable_names_and_extended_numerals(filename, path, expected):
    models = [c for c in page(filename, path).candidates if c.kind == 'tomica_model']
    assert models and all(expected in c.fields['name_original'] for c in models)
    assert all('�' not in c.fields['name_original'] for c in models)


def test_photo_identity_survives_other_rows_being_inserted():
    body = (FIXTURES / 'tomica-dream.html').read_bytes()
    before = next(c for c in page().candidates if c.kind == 'tomica_model' and c.evidence['caption'] == 'パンどろぼう')
    changed = body.replace(b'<tbody>', b'<tbody><tr><td colspan="3">new unrelated heading</td></tr>', 1)
    after = next(c for c in TomicaAdapter().parse(BASE + 'event/tiv%20dori-mutomica.html', changed).candidates if c.kind == 'tomica_model' and c.evidence['caption'] == 'パンどろぼう')
    assert after.source_key == before.source_key

def test_consecutive_photo_reference_rows_do_not_borrow_the_previous_car_name():
    parsed = page('tomica-contiguous.html', 'event/tiv%20tomikakuji.html')
    car = next(c for c in parsed.candidates if c.kind == 'tomica_model' and c.evidence['image_urls'][0].endswith('tomica collection7 127.jpg'))
    assert car.evidence['caption'] == ''
    assert car.evidence['description'] == '15-6 ダイハツ コペン'
    assert 'スバル' not in car.fields['name_original']
    assert car.fields['brand'] == 'Daihatsu'


def test_repeated_shared_aquarium_heading_keeps_all_actual_trucks():
    parsed = page('tomica-shop.html', 'special/tto%20tomicashop.html')
    models = {c.evidence['image_urls'][0].rsplit('/', 1)[-1]: c for c in parsed.candidates if c.kind == 'tomica_model'}
    for suffix in ['0602', '0603', '0605', '0606', '0608', '0609']:
        car = models['IMG_' + suffix + '.jpg']
        assert car.evidence['caption'] == '69-6 水族館トラック'
        assert car.fields['number'] == '69-6'
