import pytest

from backend.app.models import FieldOverride, SourceIdentity, TomicaModel, TomicaVariant
from backend.app.tomica_release_years import fill_missing_years, source_year


@pytest.mark.parametrize('evidence,expected', [
    ({'group': '2003.6'}, 2003),
    ({'caption': '2019/12'}, 2019),
    ({'description': '発売日：2024年11月16日'}, 2024),
    ({'raw_header': 'No.1 car 1970.8～1974.5'}, 1970),
    ({'description': 'VIETNAM H1226'}, None),
    ({'caption': '1984年ディズニープチカ復刻版'}, None),
    ({'group': '2019.6', 'caption': '2020.7'}, None),
    ({'group': '2020.13'}, None),
    ({'description': '発売日2020.13'}, None),
    ({'description': '日産 2000年式'}, None),
])
def test_year_requires_explicit_catalogue_date(evidence, expected):
    assert source_year(evidence) == expected


def retail_model(session, jan, year=None):
    url = 'https://takaratomymall.jp/shop/g/g' + jan + '/'
    model = TomicaModel(series='Tomica', number='SP', name_original='exact sourced model',
                        release_year=year, source_locator='JAN:' + jan, source_url=url)
    session.add(model)
    session.flush()
    identity = SourceIdentity(source='official', kind='product', source_key=jan,
                              entity_id=model.id, evidence={'jan': jan, 'source_url': url})
    session.add(identity)
    session.flush()
    fact = {'source_url': url, 'year': 2026, 'text': '発売日 :  | 2026年11月21日'}
    return model, identity, fact


def test_only_missing_year_is_changed_and_repeat_is_idempotent(session):
    model, _, fact = retail_model(session, '4904810950813')
    result = fill_missing_years(session, {'4904810950813': fact})
    assert result['changed_models'] == 1 and model.release_year == 2026
    assert model.release_month is None and model.name_original == 'exact sourced model'
    assert result['changes'][0]['previous_year'] is None
    assert not fill_missing_years(session, {'4904810950813': fact})['changes']


@pytest.mark.parametrize('protected', ['known', 'override', 'historical', 'wrong_url', 'wrong_year'])
def test_known_dates_manual_choices_and_ambiguous_historical_models_are_preserved(session, protected):
    model, _, fact = retail_model(session, '4904810950813', 1998 if protected == 'known' else None)
    if protected == 'override':
        session.add(FieldOverride(kind='tomica_model', entity_key=model.id, field='release_year', value=None, actor='test-admin'))
    if protected == 'historical':
        model.source_locator = '016-1'
        model.source_url = 'http://tomica.minibird.jp/t-tomica/number/001.html'
    if protected == 'wrong_url':
        fact['source_url'] = 'https://takaratomymall.jp/shop/g/g4904810228035/'
    if protected == 'wrong_year':
        fact['year'] = 2025
    session.flush()
    result = fill_missing_years(session, {'4904810950813': fact})
    assert not result['changes']
    assert model.release_year == (1998 if protected == 'known' else None)


def test_explicit_variant_date_does_not_rewrite_base_model(session):
    model, identity, fact = retail_model(session, '4904810950813', 1970)
    variant = TomicaVariant(model_id=model.id, variant_code='specific edition')
    session.add(variant)
    session.flush()
    identity.evidence = dict(identity.evidence, variant_id=variant.id)
    session.flush()
    result = fill_missing_years(session, {'4904810950813': fact})
    assert result['changed_variants'] == 1 and result['changed_models'] == 0
    assert variant.release_year == 2026 and model.release_year == 1970
    assert variant.release_month is None


def test_original_catalogue_date_requires_exact_page_and_identity(session):
    model = TomicaModel(number='SP', name_original='Disney limited',
        source_locator='edition:own-photo',
        source_url='http://tomica.minibird.jp/t-tomica/special/disney.html')
    session.add(model)
    session.flush()
    identity = SourceIdentity(source='tomica', kind='tomica_model', source_key=model.source_locator,
        entity_id=model.id, evidence={'url': model.source_url, 'group': '2003.6'})
    session.add(identity)
    session.flush()
    result = fill_missing_years(session, {})
    assert result['changed_models'] == 1 and model.release_year == 2003
    model.release_year = None
    identity.evidence = dict(identity.evidence, url='http://tomica.minibird.jp/t-tomica/special/other.html')
    session.flush()
    assert not fill_missing_years(session, {})['changes']


def test_future_collection_preserves_source_date_group_in_model_year():
    from backend.app.sources.tomica import TomicaAdapter
    body = b'''<html><title>Disney</title><table>
    <tr><td colspan="2">2003.6</td></tr>
    <tr><td>Bus A</td><td>Bus B</td></tr>
    <tr><td><img src="a.jpg"></td><td><img src="b.jpg"></td></tr>
    <tr><td>SP A bus H1226</td><td>SP B bus H1226</td></tr></table></html>'''
    page = TomicaAdapter().parse('http://tomica.minibird.jp/t-tomica/special/disney.html', body)
    models = [c for c in page.candidates if c.kind == 'tomica_model']
    assert len(models) == 2
    assert all(c.fields['release_year'] == 2003 for c in models)
    assert all(c.fields['release_month'] is None for c in models)


def test_committed_official_years_match_their_labelled_source_dates():
    import json
    import re
    from backend.app.tomica_release_years import FACTS
    facts = json.loads(FACTS.read_text(encoding='utf-8'))
    assert len(facts) == 700
    for jan, fact in facts.items():
        assert re.fullmatch(r'\d{13}', jan)
        assert fact['source_url'] == 'https://takaratomymall.jp/shop/g/g' + jan + '/'
        match = re.search(r'発売日\s*:\s*\|\s*(\d{4})年(\d{1,2})月', fact['text'])
        assert match and int(match[1]) == fact['year'] and int(match[2]) == fact['month']
