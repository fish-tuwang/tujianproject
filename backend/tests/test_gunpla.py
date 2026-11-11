from copy import deepcopy
from datetime import date
import json

import pytest
from sqlalchemy import select

from backend.app.cache import CatalogCache
from backend.app.gunpla import GunplaQuery, GunplaRepository, import_catalog
from backend.app.models import GunplaEntry, ImageAsset, Pokemon, TomicaModel
from backend.app.repository import CatalogRepository
from backend.app.sources.gunpla import parse_home
from backend.tests.test_api import client
from backend.tests.test_gunpla_source import fixture, product
from backend.tests.test_cache import MemoryRedis


@pytest.fixture
def document():
    rows = parse_home(fixture('home')) + [product('3425'), product('3027')]
    for row in rows:
        if row['kind'] == 'product':
            row['data']['sale_types'] = ['1']
    return {'schema_version': 1, 'entries': rows, 'coverage': {'complete': True}, 'errors': []}


def test_idempotent_import_preserves_old_catalogs_and_existing_image_identity(session, document):
    url = product()['data']['cover_url']
    existing = ImageAsset(source_url=url, status='ready', rights_status='approved', rights_reference='previous fixture')
    session.add_all([existing, TomicaModel(number='114', name_original='retained'), Pokemon(dex=1, name_zh='retained')])
    session.flush()
    result = import_catalog(session, document)
    assert result['created'] == len(document['entries']) and result['failed'] == 0
    revision = CatalogRepository(session).get_revision('gunpla')
    assert revision == 1 and CatalogRepository(session).get_revision('tomica') == 0
    row = session.scalar(select(GunplaEntry).where(GunplaEntry.kind == 'product', GunplaEntry.source_key == '3425'))
    assert row.data['cover_image_id'] == existing.id
    assert existing.status == 'ready' and existing.rights_status == 'approved'
    again = import_catalog(session, document)
    assert again['unchanged'] == result['created'] and again['created'] == 0
    assert CatalogRepository(session).get_revision('gunpla') == revision
    assert session.scalar(select(TomicaModel)).name_original == 'retained'
    assert session.scalar(select(Pokemon)).name_zh == 'retained'


def test_changed_gallery_bumps_only_gunpla_and_bad_records_keep_old_data(session, document):
    import_catalog(session, document)
    changed = deepcopy(document)
    changed['entries'][-1]['data']['gallery_urls'].reverse()
    report = import_catalog(session, changed)
    assert report['updated'] == 1 and CatalogRepository(session).get_revision('gunpla') == 2
    broken = deepcopy(document['entries'][-1])
    broken['data']['gallery_urls'] = ['https://evil.test/other.jpg']
    report = import_catalog(session, {'schema_version': 1, 'entries': [broken], 'errors': ['source failed']})
    assert report['failed'] == 1
    assert GunplaRepository(session).product('3027')['gallery'][0].endswith(session.scalar(select(GunplaEntry).where(GunplaEntry.source_key == '3027')).data['gallery_image_ids'][0])
    assert len(GunplaRepository(session).product('3027')['gallery']) == 10


def test_summary_and_detail_never_expose_sources_or_mix_cover_and_gallery(session, document):
    import_catalog(session, document)
    repo = GunplaRepository(session)
    rows = repo.list_products(GunplaQuery())
    assert len(rows['items']) == 2
    assert all(not {'gallery', 'gallery_urls', 'detail_images', 'source_url'} & row.keys() for row in rows['items'])
    detail = repo.product('3425')
    assert len(detail['gallery']) == 4 and detail['cover'] not in detail['gallery']
    assert detail['price_cny_text'] is None and detail['price_jpy_text'] == '1,760日元(含税)'
    assert detail['release_text'] == '2026年8月'
    assert all(url.startswith('/api/reference-images/') for url in [detail['cover'], *detail['gallery']])
    assert 'source_url' not in json.dumps(detail)
    assert not repo.product('999999999')


def test_filters_keep_all_official_model_brands_and_work_decades(session, document):
    import_catalog(session, document)
    filters = GunplaRepository(session).filters()
    assert len(filters['brands']) == 17 and filters['brands'][0]['id'] == '148'
    assert len([r for group in filters['series_groups'] for r in group['items']]) == 39
    groups = {g['id']: {r['id'] for r in g['items']} for g in filters['series_groups']}
    assert '29' in groups['1970'] and '73' in groups['1980'] and '28' in groups['1990']
    assert '22' in groups['2010']  # First overseas release, not the later Japanese broadcast.
    assert [r['id'] for r in filters['sale_types']] == ['1', '2', '3', '4']


def test_series_unifies_sale_types_and_grade_filters_are_an_intersection(session, document):
    imported = deepcopy(document)
    imported['entries'][-1]['data']['sale_types'] = ['3']
    import_catalog(session, imported)
    repo = GunplaRepository(session)
    assert repo.list_products(GunplaQuery(grade='15', sale_type='1', q='飞翼', scale='1/144'))['total'] == 1
    assert repo.list_products(GunplaQuery(grade='15', sale_type='3', q='飞翼'))['total'] == 1
    assert repo.list_products(GunplaQuery(mode='series', series='28', grade='6', sale_type='4'))['total'] == 2
    assert repo.list_products(GunplaQuery(mode='series', series='26'))['total'] == 0
    assert repo.list_products(GunplaQuery(q='ＥＮＴＲＹ　ＧＲＡＤＥ'))['total'] == 2


def test_pagination_and_queries_do_not_mutate_the_one_shared_snapshot(session, document):
    template = document['entries'][-1]
    for index in range(63):
        row = deepcopy(template)
        row['source_key'] = row['data']['official_id'] = str(5000 + index)
        row['name'] = 'synthetic boundary model ' + str(index)
        document['entries'].append(row)
    import_catalog(session, document)
    cache = CatalogCache(client=MemoryRedis())
    repo = GunplaRepository(session, cache)
    first = repo.list_products(GunplaQuery(limit=20))
    second = repo.list_products(GunplaQuery(limit=20, page=2))
    assert len(first['items']) == 20 and first['total'] == 65 and first['total_pages'] == 4
    assert set(r['id'] for r in first['items']).isdisjoint(r['id'] for r in second['items'])
    original = deepcopy(repo.summary_rows())
    repo.list_products(GunplaQuery(q='not present', limit=100))
    repo.list_products(GunplaQuery(page=999, limit=40))
    assert repo.summary_rows() == original and list(cache.snapshots) == ['gunpla']


def test_home_uses_actual_dates_and_no_outbound_links(session, document):
    import_catalog(session, document)
    repo = GunplaRepository(session)
    assert repo.home(date(2026, 8, 1))['upcoming'][0]['month'] == '2026-08'
    assert not repo.home(date(2027, 1, 1))['upcoming']
    home = repo.home(date(2026, 8, 1))
    assert home['events'] and home['announcements']
    assert 'source_url' not in json.dumps(home) and 'https://' not in json.dumps(home)


def test_private_api_contract_and_invalid_inputs(client, session, document):
    import_catalog(session, document)
    session.commit()
    assert client.get('/api/gunpla').json()['total'] == 2
    assert len(client.get('/api/gunpla/products/3425').json()['gallery']) == 4
    assert client.get('/api/gunpla/products/999999').status_code == 404
    for query in ['limit=21', 'page=0', 'grade=invalid', 'sale_type=5', 'mode=unknown', 'scale=1/0']:
        assert client.get('/api/gunpla?' + query).status_code == 422
    assert client.get('/api/gunpla/filters').status_code == 200
    assert client.get('/api/gunpla/home').status_code == 200
