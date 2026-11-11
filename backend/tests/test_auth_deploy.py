from types import SimpleNamespace
from contextlib import nullcontext
import io
import json
import subprocess
import urllib.error

import pytest
from scripts import prepare_auth, renew_tls


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(prepare_auth, 'ROOT', tmp_path)
    (tmp_path / 'app/deploy').mkdir(parents=True)
    (tmp_path / 'app/deploy/preview-nginx.conf').write_text('events {}\nhttp {\n    server {\n}\n}\n')
    (tmp_path / 'preview-nginx.conf').write_text('original config')
    return tmp_path


def test_gate_stays_closed_when_an_old_image_serves_anonymous_data(project, monkeypatch):
    prepare_auth.set_gate('closed')
    monkeypatch.setattr(prepare_auth, 'json_get', lambda url: {'status': 'ready', 'revision': '0005_gunpla'} if 'health' in url else {'items': []})
    with pytest.raises(RuntimeError, match='anonymous'):
        prepare_auth.set_gate('open')
    assert prepare_auth.gate_file().exists()


@pytest.mark.parametrize('owner', [{'username': 'owner', 'disabled': 0}, {'username': 'owner', 'disabled': 1}, None])
def test_operator_created_accounts_do_not_replace_the_required_owner_check(project, monkeypatch, owner):
    (project / '.env').write_text('APP_IMAGE=dual-catalog:0.10.0\nPROJECT_DATA_DIR=' + str(project / 'data'))
    (project / 'auth-owner.json').write_text(json.dumps({'username': 'owner'}))
    users = [{'username': 'invited', 'disabled': 0}] + ([owner] if owner else [])
    def response(url):
        if '/api/tomica' in url:
            raise urllib.error.HTTPError(url, 401, 'Unauthorized', {}, io.BytesIO(b'{"code":"AUTH_REQUIRED"}'))
        return {'status': 'ready', 'revision': '0005_gunpla'}
    monkeypatch.setattr(prepare_auth, 'json_get', response)
    monkeypatch.setattr(prepare_auth.urllib.request, 'urlopen', lambda *a, **k: nullcontext(SimpleNamespace(geturl=lambda: 'http://127.0.0.1/login/')))
    monkeypatch.setattr(prepare_auth, 'run', lambda *a, **k: SimpleNamespace(stdout=json.dumps({'users': users})))
    prepare_auth.set_gate('closed')
    if owner and not owner['disabled']:
        prepare_auth.set_gate('open')
        assert not prepare_auth.gate_file().exists()
    else:
        with pytest.raises(RuntimeError, match='owner account'):
            prepare_auth.set_gate('open')
        assert prepare_auth.gate_file().exists()


def test_invalid_configuration_never_stops_or_overwrites_existing_proxy(project, monkeypatch):
    def forbidden(*args):
        raise RuntimeError('configuration rejected')
    monkeypatch.setattr(prepare_auth, 'check_config', forbidden)
    with pytest.raises(RuntimeError):
        prepare_auth.install_challenge_proxy('local-image')
    assert (project / 'preview-nginx.conf').read_text() == 'original config'


def test_failed_proxy_rebuild_restores_only_project_proxy_with_closed_configuration(project, monkeypatch):
    calls = []
    monkeypatch.setattr(prepare_auth, 'check_config', lambda *args: None)
    def run(command, **kwargs):
        calls.append(command)
        if command[:3] == ['docker', 'run', '-d']:
            raise subprocess.CalledProcessError(1, command)
        return SimpleNamespace(returncode=0, stdout='')
    monkeypatch.setattr(prepare_auth, 'run', run)
    monkeypatch.setattr(prepare_auth.subprocess, 'run', run)
    with pytest.raises(subprocess.CalledProcessError):
        prepare_auth.install_challenge_proxy('local-image')
    assert 'return 503' in (project / 'preview-nginx.conf').read_text()
    assert any(c[:2] == ['docker', 'start'] and c[2] == prepare_auth.PROXY for c in calls)
    assert not any(name in str(calls) for name in ['fish-search', 'qq-summary-bot'])


def test_proxy_mounts_only_certificate_directories_not_acme_account_keys(project):
    mounts = [value.replace('\\', '/') for value in prepare_auth.mounts(project / 'next.conf')]
    assert any('/tls/config/live:' in value for value in mounts)
    assert any('/tls/config/archive:' in value for value in mounts)
    assert not any('/tls/config:' in value or '/accounts:' in value for value in mounts)


def test_auth_artifacts_cannot_escape_project_workspace(project):
    (project / '.env').write_text('PROJECT_DATA_DIR=' + str(project.parent / 'other-project'))
    with pytest.raises(RuntimeError, match='inside'):
        prepare_auth.artifacts('.env')


def test_failed_renewal_never_reloads_proxy(monkeypatch):
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        raise subprocess.CalledProcessError(1, command)
    monkeypatch.setattr(renew_tls.subprocess, 'run', run)
    with pytest.raises(subprocess.CalledProcessError):
        renew_tls.main(['--dry-run'])
    assert len(calls) == 1 and '--dry-run' in calls[0]


def test_successful_renewal_checks_configuration_before_only_own_proxy_reload(monkeypatch):
    calls = []
    monkeypatch.setattr(renew_tls.subprocess, 'run', lambda command, **kwargs: calls.append(command))
    assert renew_tls.main([]) == 0
    assert calls[-2] == ['docker', 'exec', 'dual-catalog-preview-proxy', 'nginx', '-t']
    assert calls[-1] == ['docker', 'exec', 'dual-catalog-preview-proxy', 'nginx', '-s', 'reload']
