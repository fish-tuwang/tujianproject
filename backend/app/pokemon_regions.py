"""Versioned regional Pokédex membership; public requests only read local data."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re

SUPPORTED_REGIONS = {'kanto': '关都', 'johto': '城都', 'hoenn': '丰缘', 'sinnoh': '神奥', 'unova': '合众', 'kalos': '卡洛斯', 'alola': '阿罗拉', 'galar': '伽勒尔', 'hisui': '洗翠', 'paldea': '帕底亚'}
DEFINITION = '同地区各版本图鉴合并收录'
DATA_PATH = Path(__file__).with_name('data') / 'pokemon-regions.json'
BASE = 'https://pokeapi.co/api/v2/'


def _version(regions):
    content = [{k: v for k, v in region.items() if k != 'collected_at'} for region in regions]
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def _resource_url(url, kind):
    if not re.fullmatch(re.escape(BASE + kind + '/') + r'[a-z0-9-]+/', url):
        raise ValueError('Unexpected regional source URL')
    return url


def build_region_index(client, collected_at):
    cache_dir = Path(__file__).resolve().parents[2] / 'artifacts' / 'ui-regions'
    cache_dir.mkdir(parents=True, exist_ok=True)
    resources = {}
    def fetch(url, filename, kind):
        _resource_url(url, kind)
        if url not in resources:
            response = client.get(url)
            response.raise_for_status()
            resources[url] = response.json()
            (cache_dir / filename).write_text(json.dumps(resources[url], ensure_ascii=False), encoding='utf-8')
        return resources[url]
    regions = []
    for key, name in SUPPORTED_REGIONS.items():
        url = BASE + 'region/' + key + '/'
        data = fetch(url, 'region-' + key + '.json', 'region')
        members, sources = set(), []
        for source in data['pokedexes']:
            if not re.fullmatch(r'[a-z0-9-]+', source['name']):
                raise ValueError('Invalid Pokédex source name')
            pokedex = fetch(source['url'], 'pokedex-' + source['name'] + '.json', 'pokedex')
            for entry in pokedex['pokemon_entries']:
                species = _resource_url(entry['pokemon_species']['url'], 'pokemon-species')
                dex = int(species.rstrip('/').rsplit('/', 1)[-1])
                if dex <= 0:
                    raise ValueError('Invalid national number')
                members.add(dex)
            sources.append({'name': source['name'], 'url': source['url'], 'version_groups': pokedex['version_groups']})
        if not members:
            raise ValueError('Empty regional index: ' + key)
        regions.append({'key': key, 'name': name, 'source_url': url, 'collected_at': collected_at, 'pokedexes': sources, 'dexes': sorted(members)})
    return {'schema_version': 1, 'definition': DEFINITION, 'index_version': _version(regions), 'collected_at': collected_at, 'regions': regions}


@lru_cache(maxsize=1)
def load_region_index():
    data = json.loads(DATA_PATH.read_text(encoding='utf-8'))
    assert data['schema_version'] == 1 and data['definition'] == DEFINITION
    assert [r['key'] for r in data['regions']] == list(SUPPORTED_REGIONS)
    assert _version(data['regions']) == data['index_version']
    for region in data['regions']:
        values = region['dexes']
        assert values and all(type(v) is int and v > 0 for v in values)
        assert values == sorted(set(values))
    return data


@lru_cache(maxsize=10)
def region_dexes(key):
    return frozenset(next(r for r in load_region_index()['regions'] if r['key'] == key)['dexes'])


def region_index_version():
    return load_region_index()['index_version']


def region_metadata():
    data = load_region_index()
    return {'definition': data['definition'], 'index_version': data['index_version'], 'items': [{**deepcopy({k: v for k, v in r.items() if k != 'dexes'}), 'species_count': len(r['dexes'])} for r in data['regions']]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh', action='store_true', required=True)
    parser.parse_args()
    import httpx
    with httpx.Client(timeout=30) as client:
        data = build_region_index(client, datetime.now(timezone.utc).isoformat())
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = DATA_PATH.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(DATA_PATH)
    print(json.dumps({'status': 'pass', 'index_version': data['index_version'], 'regions': {r['key']: len(r['dexes']) for r in data['regions']}}))


if __name__ == '__main__':
    main()
