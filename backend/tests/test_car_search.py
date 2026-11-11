import pytest
from backend.app.repository import CatalogRepository
from backend.app.schemas import SourceCandidate, TomicaQuery


@pytest.fixture
def cars(session):
    repo = CatalogRepository(session)
    rows = [
        ('064', 'トヨタ　マークX', 'Toyota'),
        ('060', 'トヨタ　マークX　個人タクシー', 'Toyota'),
        ('SP-286', 'トヨタ マークX 覆面パトロールカー', 'Toyota'),
        ('072', 'トヨタ　マーク　X', 'Toyota'),
        ('069', 'トヨタ　マークⅡ　2600　グランデ', 'Toyota'),
        ('014', 'トヨタ　カムリ', 'Toyota'),
        ('020', 'ホンダ シビック', 'Honda'),
        ('021', 'ニッサン スカイライン GT-R', 'Nissan'),
    ]
    for number, name, brand in rows:
        repo.publish_candidates(None, [SourceCandidate(kind='tomica_model', source_key=number, fields={'number': number, 'name_original': name, 'brand': brand, 'source_locator': number + '-1'})])
    return repo


@pytest.mark.parametrize('query', ['Mark x', 'MARKX', 'ＭＡＲＫ　Ｘ', 'マーク X', 'ﾏｰｸX', '丰田Mark-X', 'Toyota Mark X', 'Mark X Toyota', '锐志'])
def test_mark_x_spellings_find_all_four_without_mark_ii(cars, query):
    result = cars.list_tomica(TomicaQuery(q=query, page=1, limit=20))
    assert {item['number'] for item in result['items']} == {'064', '060', 'SP-286', '072'}
    assert result['total'] == 4


def test_compound_search_and_existing_filters(cars):
    result = cars.list_tomica(TomicaQuery(q='Toyota Mark X taxi', page=1))
    assert [item['number'] for item in result['items']] == ['060']
    assert not cars.list_tomica(TomicaQuery(q='markx', brand='Honda'))['items']
    assert {item['number'] for item in cars.list_tomica(TomicaQuery(q='mark II'))['items']} == {'069'}
    assert not cars.list_tomica(TomicaQuery(q='不存在车型'))['items']
    assert not cars.list_tomica(TomicaQuery(q='---'))['items']


def test_other_names_brands_and_identifiers(cars):
    assert [item['number'] for item in cars.list_tomica(TomicaQuery(q='Camry'))['items']] == ['014']
    assert [item['number'] for item in cars.list_tomica(TomicaQuery(q='本田 Civic'))['items']] == ['020']
    assert [item['number'] for item in cars.list_tomica(TomicaQuery(q='日产 GTR'))['items']] == ['021']
    assert [item['number'] for item in cars.list_tomica(TomicaQuery(q='SP-286-1'))['items']] == ['SP-286']
    assert cars.list_tomica(TomicaQuery(q='丰田', page=1))['total'] == 6


def test_partial_original_names_remain_searchable(cars):
    assert cars.list_tomica(TomicaQuery(q='トヨ', page=1))['total'] == 6
    assert [item['number'] for item in cars.list_tomica(TomicaQuery(q='シビ'))['items']] == ['020']
