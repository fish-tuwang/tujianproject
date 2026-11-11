import pytest
from sqlalchemy import select
from backend.app.models import FieldOverride, Pokemon, SourceIdentity, TomicaModel
from backend.app.repository import CatalogError, CatalogRepository
from backend.app.schemas import PokemonQuery, SourceCandidate, TomicaQuery


def car(key, year=None, **extra):
    return SourceCandidate(kind='tomica_model', source_key=key, fields={'number': '001', 'name_original': key, 'release_year': year, **extra})


def test_generations_and_idempotency(session):
    repo = CatalogRepository(session)
    assert repo.publish_candidates(None, [car('001-1', 1970), car('001-2', 1974)]) == 2
    rows = repo.list_tomica(TomicaQuery())['items']
    assert len(rows) == 2
    old = rows[0]['updated_at']
    assert repo.publish_candidates(None, [car('001-1', 1970)]) == 0
    assert repo.list_tomica(TomicaQuery())['items'][0]['updated_at'] == old
    assert len(list(session.scalars(select(SourceIdentity)))) == 2


def test_override_filters_cursor_and_unknown(session):
    repo = CatalogRepository(session)
    repo.publish_candidates(None, [car('first', 1970), car('second', 2020), car('unknown')])
    page = repo.list_tomica(TomicaQuery(limit=1))
    first = page['items'][0]['id']
    assert len(repo.list_tomica(TomicaQuery(year='unknown'))['items']) == 1
    with pytest.raises(CatalogError, match='分页'):
        repo.list_tomica(TomicaQuery(q='x', cursor=page['next_cursor']))
    repo.set_override('tomica_model', first, 'brand', 'Nissan')
    assert repo.get_tomica_filters()['brands'] == ['Nissan']
    assert repo.list_tomica(TomicaQuery(brand='Nissan'))['items'][0]['id'] == first
    with pytest.raises(CatalogError) as error:
        repo.list_tomica(TomicaQuery(cursor=page['next_cursor']))
    assert error.value.status == 409
    repo.publish_candidates(None, [car('first', 1970)])
    assert repo.get_tomica(first)['brand'] == 'Nissan'


def test_numeric_pokemon_and_forms(session):
    repo = CatalogRepository(session)
    for dex in [10, 2]:
        repo.publish_candidates(None, [SourceCandidate(kind='pokemon', source_key=str(dex), fields={'dex': dex, 'name_zh': str(dex)})])
    repo.publish_candidates(None, [SourceCandidate(kind='pokemon_form', source_key='2:other', fields={'dex': 2, 'form_key': 'other', 'display_name': 'other'})])
    assert [p['dex'] for p in repo.list_pokemon(PokemonQuery())['items']] == [2, 10]
    assert len(repo.get_pokemon(2)['forms']) == 1


def test_version_date_not_inherited(session):
    repo = CatalogRepository(session)
    repo.publish_candidates(None, [car('001-1', 1970), SourceCandidate(kind='tomica_variant', source_key='1-1-1', fields={'variant_code': '1-1-1'}, evidence={'model_key': '001-1'})])
    result = repo.list_tomica(TomicaQuery())['items'][0]
    assert repo.get_tomica(result['id'])['variants'][0]['release_year'] is None


def test_reference_images_do_not_claim_approved_delivery(session):
    from backend.app.models import ImageAsset
    asset=ImageAsset(source_url='http://tomica.minibird.jp/t-tomica/number/car photo.jpg')
    session.add(asset);session.flush()
    value=CatalogRepository(session).image(asset.id)
    assert value['image_url'] is None and value['image_status']=='pending'
    assert value['source_image_url'].endswith('car%20photo.jpg')
    asset.source_url='http://127.0.0.1/private.png';session.flush()
    assert CatalogRepository(session).image(asset.id)['source_image_url'] is None


def test_default_form_precedes_regional_form_for_detail_clients(session):
    repo = CatalogRepository(session)
    repo.publish_candidates(None, [SourceCandidate(kind='pokemon', source_key='37', fields={'dex': 37, 'name_zh': '六尾'})])
    for key, types in [('alola', ['冰']), ('default', ['火'])]:
        repo.publish_candidates(None, [SourceCandidate(kind='pokemon_form', source_key='37:'+key, fields={'dex': 37, 'form_key': key, 'display_name': key, 'types': types})])
    forms = repo.get_pokemon(37)['forms']
    assert [form['form_key'] for form in forms] == ['default', 'alola']
    assert forms[0]['types'] == ['火'] and forms[1]['types'] == ['冰']
