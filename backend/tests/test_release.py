import pytest
from scripts.acceptance import Blocked, assert_demo_database, load_environment, run_suite, Checks
from scripts.check_release import validate_release


@pytest.mark.parametrize('database',['dual_catalog','postgres','dual_catalog_demo_copy'])
def test_production_db_is_rejected(database):
    with pytest.raises(ValueError):assert_demo_database('postgresql://user@localhost/'+database)


def test_demo_and_environment(tmp_path,monkeypatch):
    assert_demo_database('postgresql://user@localhost/dual_catalog_demo')
    with pytest.raises(Blocked):load_environment(str(tmp_path/'missing.env'))


def test_readonly_forbids_writes():
    with pytest.raises(ValueError):run_suite('sync',None,Checks(),'http://localhost','production-readonly')


def test_production_release_does_not_pass_without_inputs():
    reasons=validate_release({'mode':'production'},evidence=True)
    assert any('AppID' in reason for reason in reasons)
    assert any('HTTPS' in reason for reason in reasons)
    assert any('coverage' in reason for reason in reasons)


def test_ip_is_not_a_production_domain():
    reasons=validate_release({'mode':'production','PUBLIC_API_BASE_URL':'https://117.72.11.77','WECHAT_APP_ID':'wx1234567890abcdef'})
    assert any('bare IP' in reason for reason in reasons)
