from types import SimpleNamespace
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app.config import Settings
from backend.app.auth import install_auth
from backend.app.tomica_maintenance import coverage, router


def test_report_is_read_only_and_limited_to_tomica(session):
    app=SimpleNamespace(state=SimpleNamespace(engine=session.get_bind()),routes=[])
    result=coverage(SimpleNamespace(app=app))
    assert {'tomica_models','tomica_variants'} <= {row['name'] for row in result['tables']}
    assert all('tomica' in row['name'] for row in result['tables'])
    assert all(row['count']==0 for row in result['tables'])


def test_report_requires_catalog_login(tmp_path):
    app=FastAPI();app.include_router(router)
    install_auth(app,Settings(_env_file=None,auth_enabled=True,auth_store_path=str(tmp_path/'accounts.sqlite3'),artifact_dir=str(tmp_path/'logs')))
    with TestClient(app) as client:
        response=client.get('/api/tomica-maintenance')
        assert response.status_code==401
        assert 'tables' not in response.text
