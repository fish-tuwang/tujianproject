from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest
from sqlalchemy.orm import sessionmaker

from backend.app.auth import COOKIE
from backend.app.auth_store import AuthError, AuthStore, hash_password, verify_password
from backend.app.config import Settings
from backend.app.main import create_app

PASSWORD = 'unit-test-password-strong-123'
NEW_PASSWORD = 'a-new-unit-password-strong-456'
CLIENT = {'X-Catalog-Client': 'web'}


@pytest.fixture
def store(tmp_path):
    value = AuthStore(tmp_path / 'auth' / 'accounts.sqlite3')
    value.create_user('owner', PASSWORD, must_change=False)
    return value


@pytest.fixture
def auth_client(tmp_path, session):
    settings = Settings(_env_file=None, database_url='sqlite://', auth_enabled=True, admin_token='unit-admin-token',
                        auth_store_path=str(tmp_path / 'auth' / 'accounts.sqlite3'),
                        artifact_dir=str(tmp_path / 'acceptance'), auth_service_token='unit-internal-service-token')
    app = create_app(settings)
    app.state.session_factory = sessionmaker(session.get_bind(), expire_on_commit=False)
    app.state.auth_store.create_user('owner', PASSWORD, must_change=False)
    with TestClient(app, base_url='https://testserver') as client:
        yield client


def signin(client, password=PASSWORD, client_name='web'):
    return client.post('/api/auth/login', json={'username': 'owner', 'password': password}, headers={'X-Catalog-Client': client_name})


def test_scrypt_has_random_salt_and_never_stores_plain_password():
    first, second = hash_password(PASSWORD), hash_password(PASSWORD)
    assert first != second and PASSWORD not in first
    assert verify_password(PASSWORD, first) and not verify_password('incorrect', first)
    assert not verify_password(PASSWORD, first.replace('32768', '1073741824'))
    with pytest.raises(AuthError):
        hash_password('short')


def test_concurrent_logins_have_only_one_winner_across_store_instances(store):
    other = AuthStore(store.path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(value.login, 'owner', PASSWORD, ip) for value, ip in [(store, 'a'), (other, 'b')]]
        tokens = [future.result()[0] for future in futures]
    assert sum(store.authenticate(token) is not None for token in tokens) == 1
    assert all(token.encode() not in store.path.read_bytes() for token in tokens)


def test_wrong_password_and_old_logout_cannot_revoke_new_session(store):
    first, _ = store.login('owner', PASSWORD, 'a')
    with pytest.raises(AuthError, match='账号或密码错误'):
        store.login('owner', 'wrong', 'b')
    assert store.authenticate(first)
    second, _ = store.login('owner', PASSWORD, 'b')
    assert store.authenticate(first) is None
    store.logout(first)
    assert store.authenticate(second)


def test_password_change_reset_disable_and_restart_revoke_correctly(store):
    old, _ = store.login('owner', PASSWORD, 'a')
    new, profile = store.change_password(old, PASSWORD, NEW_PASSWORD)
    assert not profile['must_change_password'] and store.authenticate(old) is None
    assert AuthStore(store.path).authenticate(new)
    store.reset_password('owner', PASSWORD)
    assert store.authenticate(new) is None
    last, profile = store.login('owner', PASSWORD, 'a')
    assert profile['must_change_password']
    store.disable_user('owner')
    assert store.authenticate(last) is None
    with pytest.raises(AuthError, match='账号或密码错误'):
        store.login('owner', PASSWORD, 'a')


def test_absolute_expiry_and_failed_attempt_limits(store):
    moment = [10000]
    store.clock = lambda: moment[0]
    token, _ = store.login('owner', PASSWORD, 'a')
    moment[0] += 43201
    assert store.authenticate(token) is None
    for _ in range(5):
        with pytest.raises(AuthError) as error:
            store.login('owner', 'incorrect', 'bad-ip')
        assert error.value.code == 'INVALID_CREDENTIALS'
    with pytest.raises(AuthError) as error:
        store.login('owner', PASSWORD, 'bad-ip')
    assert error.value.status == 429 and error.value.retry_after == 300
    moment[0] += 301
    assert store.login('owner', PASSWORD, 'bad-ip')[0]


def test_anonymous_routes_and_images_cannot_bypass_auth(auth_client):
    for path in ['/api/tomica', '/api/pokemon', '/api/pokemon/regions', '/api/reference-images/00000000-0000-0000-0000-000000000000', '/preview/news-assets/example.jpg', '/preview/app.js', '/openapi.json']:
        response = auth_client.get(path, headers={'If-None-Match': '"cached"'})
        assert response.status_code == 401, path
        assert response.json()['code'] == 'AUTH_REQUIRED'
        assert 'no-store' in response.headers['cache-control']
    response = auth_client.get('/preview/?catalog=tomica', follow_redirects=False)
    assert response.status_code == 303 and response.headers['location'].startswith('/login/')
    assert auth_client.get('/health/live').status_code == 200


def test_cookie_flags_login_rotation_and_old_logout(auth_client):
    response = signin(auth_client)
    assert response.status_code == 200 and 'access_token' not in response.json()
    header = response.headers['set-cookie'].lower()
    assert all(value in header for value in ['httponly', 'secure', 'samesite=lax', 'path=/'])
    first = auth_client.cookies.get(COOKIE)
    response = signin(auth_client, client_name='miniprogram')
    second = response.json()['access_token']
    assert first != second
    assert auth_client.get('/api/auth/me', headers={'Authorization': 'Bearer ' + first}).status_code == 401
    auth_client.post('/api/auth/logout', json={}, headers={**CLIENT, 'Authorization': 'Bearer ' + first})
    assert auth_client.get('/api/auth/me', headers={'Authorization': 'Bearer ' + second}).status_code == 200


def test_first_password_change_is_required_before_catalog_or_cached_images(auth_client):
    auth_client.app.state.auth_store.reset_password('owner', PASSWORD)
    response = signin(auth_client)
    assert response.json()['must_change_password']
    old = auth_client.cookies.get(COOKIE)
    for path in ['/api/tomica', '/api/reference-images/00000000-0000-0000-0000-000000000000', '/preview/news-assets/a.jpg']:
        assert auth_client.get(path).status_code == 403
    response = auth_client.get('/preview/', follow_redirects=False)
    assert response.status_code == 303 and response.headers['location'].startswith('/account/')
    assert auth_client.get('/api/auth/me').status_code == 200
    response = auth_client.post('/api/auth/password', json={'current_password': PASSWORD, 'new_password': NEW_PASSWORD}, headers=CLIENT)
    assert response.status_code == 200 and not response.json()['must_change_password']
    assert auth_client.get('/api/auth/me', headers={'Authorization': 'Bearer ' + old}).status_code == 401
    assert auth_client.get('/api/tomica').status_code == 200


def test_cross_site_requests_and_registration_are_rejected(auth_client):
    payload = {'username': 'owner', 'password': PASSWORD}
    assert auth_client.post('/api/auth/login', json=payload).status_code == 403
    assert auth_client.post('/api/auth/login', json=payload, headers={**CLIENT, 'Origin': 'https://other.test'}).status_code == 403
    assert signin(auth_client).status_code == 200
    assert auth_client.post('/api/auth/register', json=payload, headers=CLIENT).status_code == 404
    assert len(auth_client.app.state.auth_store.list_users()) == 1


def test_wrong_current_password_does_not_destroy_valid_login(auth_client):
    signin(auth_client)
    response = auth_client.post('/api/auth/password', json={'current_password': 'incorrect', 'new_password': NEW_PASSWORD}, headers=CLIENT)
    assert response.status_code == 403 and response.json()['code'] == 'INVALID_CURRENT_PASSWORD'
    assert auth_client.get('/api/auth/me').status_code == 200


def test_internal_service_is_read_only_loopback_and_does_not_bypass_accounts(auth_client):
    app = auth_client.app
    headers = {'X-Catalog-Service': 'unit-internal-service-token'}
    assert auth_client.get('/api/tomica', headers=headers).status_code == 401
    with TestClient(app, base_url='https://testserver', client=('127.0.0.1', 1234)) as local:
        assert local.get('/api/tomica', headers=headers).status_code == 200
        assert local.get('/api/tomica', headers={'X-Catalog-Service': 'wrong'}).status_code == 401
        assert local.get('/api/auth/me', headers=headers).status_code == 401
        assert local.post('/api/tomica', json={}, headers=headers).status_code == 401
        assert local.get('/api/admin/issues', headers=headers).status_code == 401
        assert local.get('/api/admin/issues', headers={'Authorization': 'Bearer unit-admin-token'}).status_code == 200


def test_cli_generated_credentials_are_private_and_existing_file_is_preserved(tmp_path, monkeypatch, capsys):
    from backend.app import auth_cli
    settings = Settings(_env_file=None, auth_store_path=str(tmp_path / 'auth' / 'accounts.sqlite3'), artifact_dir=str(tmp_path / 'acceptance'))
    monkeypatch.setattr(auth_cli, 'Settings', lambda: settings)
    output = tmp_path / 'private' / 'initial.json'
    args = ['create-user', 'operator', '--generate', '--output-file', str(output)]
    assert auth_cli.main(args) == 0
    data = json.loads(output.read_text(encoding='utf-8'))
    assert data['username'] == 'operator' and len(data['password']) >= 15
    assert data['password'] not in capsys.readouterr().out
    before = output.read_bytes()
    with pytest.raises(FileExistsError):
        auth_cli.main(args)
    assert output.read_bytes() == before


def test_authentication_failure_never_reuses_catalog_cache(auth_client, session):
    from backend.app.cache import CatalogCache
    from backend.tests.test_cache import MemoryRedis
    auth_client.app.state.cache = CatalogCache(client=MemoryRedis())
    signin(auth_client)
    assert auth_client.get('/api/tomica').status_code == 200
    assert auth_client.get('/api/tomica').headers['x-catalog-cache'] == 'hit'
    auth_client.cookies.clear()
    assert auth_client.get('/api/tomica').status_code == 401


def test_private_auth_log_contains_events_but_no_password_or_session(auth_client):
    signin(auth_client)
    old = auth_client.cookies.get(COOKIE)
    auth_client.post('/api/auth/password', json={'current_password': PASSWORD, 'new_password': NEW_PASSWORD}, headers=CLIENT)
    current = auth_client.cookies.get(COOKIE)
    auth_client.post('/api/auth/logout', json={}, headers=CLIENT)
    path = Path(auth_client.app.state.settings.artifact_dir).parent / 'logs/auth.jsonl'
    text = path.read_text(encoding='utf-8')
    for secret in [PASSWORD, NEW_PASSWORD, old, current]:
        assert secret not in text
    assert {'login_succeeded', 'password_changed', 'logout_succeeded'} <= {json.loads(line)['event'] for line in text.splitlines()}


def test_gunpla_remains_private_and_legacy_document_clients_redirect(auth_client):
    assert auth_client.get('/preview/gunpla.html', follow_redirects=False).status_code == 303
    assert auth_client.get('/api/gunpla').status_code == 401
    headers = {'X-Catalog-Service': 'unit-internal-service-token'}
    assert auth_client.get('/api/gunpla', headers=headers).status_code == 401
    with TestClient(auth_client.app, base_url='https://testserver', client=('127.0.0.1', 1234)) as local:
        assert local.get('/api/gunpla', headers=headers).status_code == 200
        assert local.post('/api/gunpla', headers=headers).status_code == 401
        assert local.get('/api/auth/me', headers=headers).status_code == 401
