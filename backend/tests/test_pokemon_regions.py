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


def test_wiki_regions_partition_the_full_national_catalog_without_overlap():
    data = region_metadata()
    assert len(data['items']) == 11
    assert data['definition'] == '按 Wiki 全国图鉴编号分段归类'
    all_dexes = [dex for r in data['items'] for dex in region_dexes(r['key'])]
    assert len(all_dexes) == len(set(all_dexes)) == 1025
    assert sorted(all_dexes) == list(range(1, 1026))
    assert 25 in region_dexes('kanto') and 25 not in region_dexes('paldea')
    assert region_dexes('unknown') == {808, 809}
    assert 809 not in region_dexes('kanto') | region_dexes('alola')
    assert region_dexes('hisui') == set(range(899, 906))
    assert 899 not in region_dexes('galar')
    assert len(region_dexes('kalos')) == 72 and 1000 not in region_dexes('kalos')
    assert 1000 in region_dexes('paldea')
    assert next(r for r in data['items'] if r['key'] == 'johto')['national_range'] == [152, 251]
    assert all(r['source_url'].startswith('https://wiki.52poke.com/') for r in data['items'])
    assert all('dexes' not in r and r['species_count'] > 0 for r in data['items'])
    data['items'][0]['name'] = 'changed'
    assert region_metadata()['items'][0]['name'] == '关都'
    assert isinstance(region_dexes('kanto'), frozenset)


def test_region_query_normalizes_and_rejects_unknown():
    assert PokemonQuery(region=' KANTO ').region == 'kanto'
    assert PokemonQuery(region='  ').region is None
    with pytest.raises(ValidationError):
        PokemonQuery(region='somewhere')


def test_index_builder_is_offline_and_ignores_collection_time_in_cache_version():
    from backend.app import pokemon_regions as module
    a = module.build_region_index('date-one')
    b = module.build_region_index('date-two')
    assert next(r for r in a['regions'] if r['key'] == 'kanto')['dexes'] == list(range(1, 152))
    assert a['index_version'] == b['index_version']
    assert a['schema_version'] == 2


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
    result = repo.list_pokemon(PokemonQuery(region='kanto', type='电', q='皮卡'))
    assert result['total'] == 1 and result['items'][0]['dex'] == 25
    assert repo.list_pokemon(PokemonQuery(region='paldea', q='皮卡'))['total'] == 0
    assert repo.list_pokemon(PokemonQuery(region='kalos', q='赛富豪'))['total'] == 0
    assert repo.list_pokemon(PokemonQuery(region='paldea', type='钢', q='赛富豪'))['items'][0]['dex'] == 1000
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
    assert meta.status_code == 200 and len(meta.json()['items']) == 11
    assert client.get('/api/pokemon?region=invalid').status_code == 422
    first = client.get('/api/pokemon?region=kanto&type=电')
    assert first.status_code == 200 and first.json()['total'] == 1
    assert first.headers['x-catalog-cache'] == 'miss'
    assert client.get('/api/pokemon?region=kanto&type=电').headers['x-catalog-cache'] == 'hit'
    assert client.get('/api/pokemon?region=paldea&type=电').headers['x-catalog-cache'] == 'miss'
