from pathlib import Path
from bs4 import BeautifulSoup
from sqlalchemy import select
from backend.app.config import Settings
from backend.app.models import ImageAsset, PokemonDetail
from backend.app.repository import CatalogRepository
from backend.app.schemas import PokemonQuery
from backend.app.sources.pokemon import PokemonAdapter
from backend.app.sources.pokemon_details import parse_details
from backend.app.sync.service import SyncService

FIXTURES = Path(__file__).parent / 'fixtures'


def details(filename):
    return parse_details(BeautifulSoup((FIXTURES / filename).read_text(encoding='utf-8'), 'html.parser'), 'https://wiki.52poke.com/zh-hans/妙蛙种子')


def test_stats_are_base_values_not_level_ranges():
    data = details('pokemon-detail.html')
    assert [s['value'] for s in data['base_stats'][0]['stats']] == [45, 49, 49, 65, 65, 45]
    assert data['base_stats'][0]['total'] == 318


def test_super_evolution_stats_keep_their_form_labels():
    groups = details('pokemon-006.html')['base_stats']
    assert [g['total'] for g in groups] == [534, 634, 634]
    assert len({g['label'] for g in groups}) == 3
    assert 'X' in groups[1]['label'] and 'Y' in groups[2]['label']


def test_acquisition_rowspan_and_regional_form_are_retained():
    rows = details('pokemon-forms.html')['acquisition']
    assert any(r['games'] == '绿' and '7' in r['location'] and r['method'] == '随机' for r in rows)
    assert any('阿罗拉' in r['form'] and '朱' in r['games'] and r['method'] == '太晶团体战' for r in rows)
    assert any('传入' in r['location'] and not r['method'] for r in rows)


def test_matchups_keep_inverse_and_ability_contexts():
    rows = details('pokemon-forms.html')['matchups']
    fire_immune = next(r for r in rows if '引火' in r['label'] and '反转' not in r['label'])
    assert next(t['multiplier'] for t in fire_immune['types'] if t['name'] == '火') == '0'
    assert any('反转' in r['label'] for r in rows)
    bulbasaur = details('pokemon-detail.html')['matchups'][0]
    assert next(t['multiplier'] for t in bulbasaur['types'] if t['name'] == '草') == '1/4'


def test_traditional_section_title_in_simplified_source_page():
    groups = details('pokemon-723.html')['matchups']
    assert groups and len(groups[0]['types']) == 18
    assert next(t['multiplier'] for t in groups[0]['types'] if t['name'] == '冰') == '4'


def test_moves_keep_game_columns_and_machine_codes_separate():
    groups = details('pokemon-detail.html')['movesets']
    scarlet = next(g for g in groups if '朱' in g['game'] and g['kind'] == 'machine')
    assert scarlet['moves'][0]['learn'] == '招式学习器001'
    assert scarlet['moves'][0]['name'] == '猛撞'
    assert scarlet['moves'][0]['accuracy'] == '85'
    za = next(g for g in groups if 'Z-A' in g['game'] and g['kind'] == 'machine')
    assert za['moves'][0]['cooldown'] == '10'
    assert za['moves'][0]['accuracy'] is None and za['moves'][0]['pp'] is None
    assert any(g['method'] == '蛋招式' for g in groups)


def test_regional_moves_are_not_combined():
    groups = details('pokemon-forms.html')['movesets']
    normal = next(g for g in groups if g['kind'] == 'learn' and g['form'] == '一般')
    alola = next(g for g in groups if g['kind'] == 'learn' and '阿罗拉' in g['form'])
    assert '火花' in [m['name'] for m in normal['moves']]
    assert '火花' not in [m['name'] for m in alola['moves']]


def test_shiny_pair_uses_same_game_and_exact_form():
    pairs = details('pokemon-forms.html')['shiny_pairs']
    assert len(pairs) == 2
    assert 'HOME_037A.png' in pairs[1]['normal_source_url']
    assert 'HOME_037A_s.png' in pairs[1]['shiny_source_url']
    assert pairs[1]['form'] == '阿罗拉的样子'


def test_pikachu_multiple_normal_rows_pair_with_corresponding_shiny_rows():
    pairs = details('pokemon-025.html')['shiny_pairs']
    assert len(pairs) == 11
    male = next(p for p in pairs if p['form'] == '雄性')
    female = next(p for p in pairs if p['form'] == '雌性')
    assert 'HOME_025_s.png' in male['shiny_source_url']
    assert 'HOME_025_f_s.png' in female['shiny_source_url']


def test_unown_keeps_all_twenty_eight_letter_form_pairs():
    pairs = details('pokemon-201.html')['shiny_pairs']
    assert len(pairs) == 28
    assert len({pair['form'] for pair in pairs}) == 28
    assert len({pair['shiny_source_url'] for pair in pairs}) == 28


def test_detail_ingestion_is_idempotent_and_does_not_bloat_lists(session):
    page = PokemonAdapter().parse('https://wiki.52poke.com/zh-hans/妙蛙种子', (FIXTURES / 'pokemon-detail.html').read_bytes())
    service = SyncService(session, Settings())
    service.attach_images(page, session)
    repo = CatalogRepository(session)
    assert repo.publish_candidates(None, page.candidates, source='pokemon') > 0
    assert repo.publish_candidates(None, page.candidates, source='pokemon') == 0
    assert len(list(session.scalars(select(PokemonDetail)))) == 1
    result = repo.get_pokemon(1)
    pair = result['extra']['shiny_pairs'][0]
    assert pair['normal']['preview_image_url'].startswith('/api/reference-images/')
    assert pair['shiny']['source_image_url'] != pair['normal']['source_image_url']
    assert session.get(ImageAsset, pair['normal_image_id'])
    assert 'extra' not in repo.list_pokemon(PokemonQuery())['items'][0]
    assert 'data' not in repo.list_pokemon(PokemonQuery())['items'][0]
