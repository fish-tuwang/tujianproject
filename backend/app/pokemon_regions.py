"""Wiki national-number region groups; public requests only read local data."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
from pathlib import Path

REGION_RANGES = {
    'kanto': ('关都', 1, 151), 'johto': ('城都', 152, 251),
    'hoenn': ('丰缘', 252, 386), 'sinnoh': ('神奥', 387, 493),
    'unova': ('合众', 494, 649), 'kalos': ('卡洛斯', 650, 721),
    'alola': ('阿罗拉', 722, 807), 'galar': ('伽勒尔', 810, 898),
    'hisui': ('洗翠', 899, 905), 'paldea': ('帕底亚', 906, 1025),
    'unknown': ('未确认', 808, 809),
}
SUPPORTED_REGIONS = {key: value[0] for key, value in REGION_RANGES.items()}
DEFINITION = '按 Wiki 全国图鉴编号分段归类'
DATA_PATH = Path(__file__).with_name('data') / 'pokemon-regions.json'
SOURCE_URL = 'https://wiki.52poke.com/zh-hans/宝可梦列表（Pokémon_GO）'
NATIONAL_SOURCE_URL = 'https://wiki.52poke.com/zh-hans/宝可梦列表（按全国图鉴编号）'


def _version(regions):
    content = [{k: v for k, v in region.items() if k != 'collected_at'} for region in regions]
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def build_region_index(collected_at):
    # These groups match the Wiki's region headings, while keeping every species
    # in the national catalog rather than filtering to Pokémon GO releases.
    regions = [{'key': key, 'name': name, 'source_url': SOURCE_URL,
                'collected_at': collected_at, 'national_range': [first, last],
                'dexes': list(range(first, last + 1))}
               for key, (name, first, last) in REGION_RANGES.items()]
    return {'schema_version': 2, 'definition': DEFINITION, 'national_source_url': NATIONAL_SOURCE_URL,
            'index_version': _version(regions), 'collected_at': collected_at, 'regions': regions}


@lru_cache(maxsize=1)
def load_region_index():
    data = json.loads(DATA_PATH.read_text(encoding='utf-8'))
    assert data['schema_version'] == 2 and data['definition'] == DEFINITION
    assert [r['key'] for r in data['regions']] == list(SUPPORTED_REGIONS)
    assert _version(data['regions']) == data['index_version']
    for region in data['regions']:
        values = region['dexes']
        _, first, last = REGION_RANGES[region['key']]
        assert values and all(type(v) is int and v > 0 for v in values)
        assert region['national_range'] == [first, last]
        assert values == list(range(first, last + 1))
    members = [dex for region in data['regions'] for dex in region['dexes']]
    assert sorted(members) == list(range(1, 1026))
    return data


@lru_cache(maxsize=len(SUPPORTED_REGIONS))
def region_dexes(key):
    return frozenset(next(r for r in load_region_index()['regions'] if r['key'] == key)['dexes'])


def region_index_version():
    return load_region_index()['index_version']


def region_metadata():
    data = load_region_index()
    return {'definition': data['definition'], 'index_version': data['index_version'], 'national_source_url': data['national_source_url'], 'items': [{**deepcopy({k: v for k, v in r.items() if k != 'dexes'}), 'species_count': len(r['dexes'])} for r in data['regions']]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh', action='store_true', required=True)
    parser.parse_args()
    data = build_region_index(datetime.now(timezone.utc).isoformat())
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = DATA_PATH.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(DATA_PATH)
    print(json.dumps({'status': 'pass', 'index_version': data['index_version'], 'regions': {r['key']: len(r['dexes']) for r in data['regions']}}))


if __name__ == '__main__':
    main()
