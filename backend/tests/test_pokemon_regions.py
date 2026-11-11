import base64
import hashlib
import json

import pytest
from pydantic import ValidationError
from backend.app.pokemon_regions import region_dexes, region_metadata
from backend.app.repository import CatalogError, CatalogRepository
from backend.app.schemas import PokemonQuery, SourceCandidate
from backend.tests.test_api import client


def seed_regions(session):
    repo = CatalogRepository(session)
    for dex, name, types in [(1, '妙蛙种子', ['草', '毒']), (25, '皮卡丘', ['电']), (54, '可达鸭', ['水']), (133, '伊布', ['一般']), (906, '新叶喵', ['草']), (1000, '赛富豪', ['钢', '幽灵'])]:
        repo.publish_candidates(None, [SourceCandidate(kind='pokemon', source_key=str(dex), fields={'dex': dex, 'name_zh': name, 'types': types})])
    session.commit()
    return repo


def test_regional_members_overlap_and_include_current_version_expansions():
    data = region_metadata()
    assert len(data['items']) == 10
    assert data['definition'] == '同地区各版本图鉴合并收录'
    assert 25 in region_dexes('kanto') & region_dexes('paldea')
    assert 809 in region_dexes('kanto')  # Let's Go addition, not generation ranges.
    assert 1000 not in region_dexes('kanto') and 1000 in region_dexes('kalos')
    assert 1000 in region_dexes('paldea')
    assert {'lumiose-city', 'hyperspace'} <= {p['name'] for p in next(r for r in data['items'] if r['key'] == 'kalos')['pokedexes']}
    assert all('dexes' not in r and r['species_count'] > 0 for r in data['items'])
    data['items'][0]['name'] = 'changed'
    assert region_metadata()['items'][0]['name'] == '关都'
    assert isinstance(region_dexes('kanto'), frozenset)


def test_region_query_normalizes_and_rejects_unknown():
    assert PokemonQuery(region=' KANTO ').region == 'kanto'
    assert PokemonQuery(region='  ').region is None
    with pytest.raises(ValidationError):
        PokemonQuery(region='somewhere')


def test_index_builder_uses_national_species_not_regional_entry_numbers(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from backend.app import pokemon_regions as module
    # Isolate downloaded fixture writes; the builder still consumes source-shaped JSON.
    monkeypatch.setattr(module, '__file__', str(tmp_path / 'backend' / 'app' / 'pokemon_regions.py'))
    calls = []
    def get(url):
        calls.append(url)
        value = {'pokedexes': [{'name': 'test', 'url': module.BASE + 'pokedex/2/'}]} if '/region/' in url else {'pokemon_entries': [{'entry_number': 1, 'pokemon_species': {'url': module.BASE + 'pokemon-species/25/'}}, {'entry_number': 2, 'pokemon_species': {'url': module.BASE + 'pokemon-species/25/'}}], 'version_groups': []}
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: value)
    a = module.build_region_index(SimpleNamespace(get=get), 'date-one')
    b = module.build_region_index(SimpleNamespace(get=get), 'date-two')
    assert all(r['dexes'] == [25] for r in a['regions'])
    assert a['index_version'] == b['index_version']
    assert calls.count(module.BASE + 'pokedex/2/') == 2  # Once per complete build.


def test_region_cursor_invalidates_when_the_offline_index_changes(session, monkeypatch):
    from backend.app import pokemon_regions as module
    repo = seed_regions(session)
    first = repo.list_pokemon(PokemonQuery(region='kanto', limit=1))
    monkeypatch.setattr(module, 'region_index_version', lambda: 'new-index')
    with pytest.raises(CatalogError, match='分页'):
        repo.list_pokemon(PokemonQuery(region='kanto', cursor=first['next_cursor']))


def test_region_attribute_and_search_intersect_without_mutating_snapshot(session):
    repo = seed_regions(session)
    before = repo.catalog_rows('pokemon')
    assert [i['dex'] for i in repo.list_pokemon(PokemonQuery(region='kanto'))['items']] == [1, 25, 54, 133]
    result = repo.list_pokemon(PokemonQuery(region='paldea', type='电', q='皮卡'))
    assert result['total'] == 1 and result['items'][0]['dex'] == 25
    assert repo.list_pokemon(PokemonQuery(region='kanto', q='#1000'))['total'] == 0
    assert repo.catalog_rows('pokemon') == before


def test_region_cursor_binds_filter_and_old_unfiltered_cursor_remains_valid(session):
    repo = seed_regions(session)
    page = repo.list_pokemon(PokemonQuery(region='kanto', limit=2))
    assert page['total'] == 4 and page['next_cursor']
    second = repo.list_pokemon(PokemonQuery(region='kanto', limit=2, cursor=page['next_cursor']))
    assert [i['dex'] for i in second['items']] == [54, 133]
    assert second['next_cursor'] is None and second['total'] == 4
    with pytest.raises(CatalogError, match='分页'):
        repo.list_pokemon(PokemonQuery(region='paldea', cursor=page['next_cursor']))
    old = {'sort_key': [25], 'filter_hash': hashlib.sha256(json.dumps({'q': None, 'type': None}, sort_keys=True, ensure_ascii=False).encode()).hexdigest(), 'revision': 0}
    cursor = base64.urlsafe_b64encode(json.dumps(old).encode()).decode()
    assert repo.list_pokemon(PokemonQuery(cursor=cursor))['items'][0]['dex'] == 54


def test_regional_api_metadata_route_validation_and_cache(client, session):
    from backend.app.cache import CatalogCache
    from backend.tests.test_cache import MemoryRedis
    seed_regions(session)
    client.app.state.cache = CatalogCache(client=MemoryRedis())
    meta = client.get('/api/pokemon/regions')
    assert meta.status_code == 200 and len(meta.json()['items']) == 10
    assert client.get('/api/pokemon?region=invalid').status_code == 422
    first = client.get('/api/pokemon?region=kanto&type=电')
    assert first.status_code == 200 and first.json()['total'] == 1
    assert first.headers['x-catalog-cache'] == 'miss'
    assert client.get('/api/pokemon?region=kanto&type=电').headers['x-catalog-cache'] == 'hit'
    assert client.get('/api/pokemon?region=paldea&type=电').headers['x-catalog-cache'] == 'miss'
