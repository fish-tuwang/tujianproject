from copy import deepcopy
from types import SimpleNamespace

from backend.app.gunpla import GunplaQuery, GunplaRepository, series_groups
from backend.app.gunpla_classification import classification, excluded_product, product_series
from backend.app.models import GunplaEntry
from backend.app.sources.gunpla import BASE, parse_listing, parse_product
from backend.tests.test_gunpla_source import fixture


def test_fazz_variants_belong_to_sentinel_not_zz():
    assert product_series('2372', 'MG 1/100 FAZZ Ver.Ka', []) == ['89']
    assert product_series('511', 'MG 1/100 高达基地限定 FAZZ Ver.Ka（钛合金涂装版）', ['89']) == ['89']
    assert product_series('2372', 'MG 1/100 FAZZ Ver.Ka', ['119']) == ['89']
    assert product_series('2372', 'unrelated replacement product', ['119']) == ['119']


def test_years_keep_official_animation_basis_and_fill_printed_crossbone():
    rows=[SimpleNamespace(source_key=k,name=k,data={}) for k in ['89','119','104','900001','900002','900003']]
    groups={r['id']:{i['id'] for i in r['items']} for r in series_groups(rows)}
    assert {'89','119'} <= groups['1980']
    assert {'104','900001','900002','900003'} <= groups['1990']


def test_existing_database_rows_are_corrected_without_writing_back(session):
    row=GunplaEntry(kind='product',source_key='2372',name='MG 1/100 FAZZ Ver.Ka',content_hash='before',data={'series_ids':[], 'brand_ids':['13'],'sale_types':['1']})
    session.add(row);session.flush();before=deepcopy(row.data)
    repo=GunplaRepository(session)
    assert repo.list_products(GunplaQuery(mode='series',series='89'))['total']==1
    assert repo.list_products(GunplaQuery(mode='series',series='119'))['total']==0
    works={w['id'] for g in repo.filters()['series_groups'] for w in g['items']}
    assert '89' in works
    assert row.data==before and row.content_hash=='before'


def test_supplemental_works_and_unassigned_models_remain_reachable(session):
    for key,name in [('3461','MG 1/100 高达RX-78GP01'),('999000','Unverified collaboration')]:
        session.add(GunplaEntry(kind='product',source_key=key,name=name,content_hash='before',data={'series_ids':[],'brand_ids':['13'],'sale_types':['1']}))
    session.flush();repo=GunplaRepository(session)
    assert repo.list_products(GunplaQuery(mode='series',series='900001'))['total']==1
    assert repo.list_products(GunplaQuery(mode='series',series='999999'))['total']==1
    works={w['id'] for g in repo.filters()['series_groups'] for w in g['items']}
    assert {'900001','999999'} <= works


def test_official_listing_context_survives_missing_detail_link():
    url=BASE+'/index/index/series/cate/89'
    listing=parse_listing(url,fixture('eg'))['items'][0]
    assert listing['series_ids']==['89']
    body=fixture('detail-3425')
    from bs4 import BeautifulSoup
    root=BeautifulSoup(body,'html.parser')
    for a in root.select('.pg-products__linkWrap a[href*="/series/"]'):a.decompose()
    parsed=parse_product(BASE+'/index/index/detail/id/3425',str(root),listing)
    assert parsed['data']['series_ids']==['89']


def test_evidence_table_has_named_work_targets_and_identity_guards():
    facts,version=classification()
    assert len(version)==16
    for key,row in facts['products'].items():
        assert key.isdigit() and row['name'] and row['evidence_urls']
        assert row['series_ids'] and all(work in facts['series'] for work in row['series_ids'])
    assert excluded_product('471','高达基地限定 MG 1/100 MS整备架')=='standalone_accessory'
    assert excluded_product('471','different real model') is None


def test_old_shared_snapshot_is_not_reused_after_classification_release(session):
    from backend.app.cache import CatalogCache
    from backend.app.repository import CatalogRepository
    from backend.tests.test_cache import MemoryRedis
    session.add(GunplaEntry(kind='product',source_key='2372',name='MG 1/100 FAZZ Ver.Ka',content_hash='before',data={'series_ids':[],'brand_ids':['13'],'sale_types':['1']}))
    session.flush()
    cache=CatalogCache(client=MemoryRedis())
    revision=CatalogRepository(session).get_revision('gunpla')
    cache.set_json(f'rows:gunpla:{revision}',[{'id':'stale','series_ids':[]}])
    assert GunplaRepository(session,cache).summary_rows()[0]['series_ids']==['89']


def test_build_fighters_model_is_not_moved_to_seed_by_an_unrelated_id():
    assert product_series('885','HGBF 1/144 魔王X高达',['34'])==['34']
    assert product_series('3530','MG 1/100 扎古布雷型',[])==['900016']
