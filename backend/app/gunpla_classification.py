"""Evidence-backed read projection for missing official Gunpla work links.

Keeps original database/import facts intact so Mac updates need no data migration.
"""
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
from types import SimpleNamespace
import unicodedata

DATA = Path(__file__).resolve().parents[1] / 'data/gunpla-classification.json'


def identity(name):
    return re.sub(r'[\W_]+', '', unicodedata.normalize('NFKC', name).casefold())


@lru_cache(maxsize=1)
def classification():
    body = DATA.read_bytes()
    years = (DATA.parent / 'gunpla-series-years.json').read_bytes()
    return json.loads(body), hashlib.sha256(body + years).hexdigest()[:16]


def product_series(key, name, original):
    facts = classification()[0]['products'].get(str(key))
    if facts and identity(facts['name']) == identity(name):
        return list(facts['series_ids'])
    return list(original or ['999999'])


def work_rows(rows, used):
    result = list(rows)
    known = {row.source_key for row in result}
    for key, facts in classification()[0]['series'].items():
        if key not in known and key in used:
            result.append(SimpleNamespace(source_key=key, name=facts['name'], data={}))
    return result


def excluded_product(key, name):
    facts = classification()[0].get('excluded_products', {}).get(str(key))
    return facts['reason'] if facts and identity(facts['name']) == identity(name) else None
