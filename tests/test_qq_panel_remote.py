from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app.qq_panel import router,remote_html


def test_remote_panel_denies_other_users_and_all_mutations():
    app=FastAPI();app.include_router(router)
    @app.middleware('http')
    async def identity(request,next):
        request.state.identity={'username':request.headers.get('x-test-user','')}
        return await next(request)
    with TestClient(app) as client:
        assert client.get('/qq-panel/api/local-core').status_code==403
        assert client.get('/qq-panel/api/local-core',headers={'x-test-user':'other'}).status_code==403
        assert client.post('/qq-panel/api/local-core',headers={'x-test-user':'peyro-gogogo'},json={'action':'reset_mood'}).status_code==403


def test_all_native_root_links_stay_authenticated():
    page=remote_html('''<body><a href="/local-core">管理</a><img src="/sticker?f=a"><script>fetch('/api/overview');const x=`/api/local-core`;const y='https://example.com';</script>''')
    assert 'href="/qq-panel/local-core"' in page
    assert "fetch('/qq-panel/api/overview')" in page
    assert '`/qq-panel/api/local-core`' in page
    assert 'https://example.com' in page and '所有者面板' in page
    assert "'/100分'" in remote_html("<script>const denominator='/100分';</script>")
    assert 'href="/qq-panel/"' in remote_html('<a href="/">返回</a>')
    assert '"/"+3' in remote_html('<script>const ratio="/"+3;</script>')


def test_mac_entry_resolves_to_authenticated_namespace():
    app=FastAPI();app.include_router(router)
    with TestClient(app) as client:
        response=client.get('/mac-mini/qq-panel/local-core',follow_redirects=False)
        assert response.status_code==307
        assert response.headers['location']=='/qq-panel/local-core'
