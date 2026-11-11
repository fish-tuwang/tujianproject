import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest
from scripts import deploy_release, gunpla_ops, prepare_auth

FILES = ['Dockerfile.release', 'backend/app/audit.py', 'backend/app/repository.py', 'backend/app/sync/service.py', 'backend/app/worker.py', 'deploy/preview-nginx.conf', 'backend/app/auth_store.py', 'backend/app/auth.py', 'backend/app/auth_cli.py', 'backend/app/gunpla.py', 'backend/app/sources/gunpla.py', 'backend/migrations/versions/0005_gunpla.py']


@pytest.fixture
def project(tmp_path):
    for env, folder in [('.env', 'data'), ('.env.demo', 'demo')]:
        (tmp_path / env).write_text('APP_IMAGE=dual-catalog:0.10.0\nAUTH_ENABLED=true\nPROJECT_DATA_DIR=' + str(tmp_path / folder) + '\nDATABASE_URL=postgresql+psycopg://catalog:private%21@127.0.0.1:5432/catalog\n')
        (tmp_path / folder / 'artifacts/acceptance').mkdir(parents=True)
    for name in FILES:
        target = tmp_path / 'app' / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_text('source')
    (tmp_path / 'auth-owner.json').write_text('{"username":"owner"}')
    source = tmp_path / 'data/artifacts/gunpla-source/catalog.json'; source.parent.mkdir()
    source.write_text(json.dumps({'schema_version': 1, 'entries': [{'kind': 'product'}], 'coverage': {'status': 'running'}}))
    return tmp_path


@pytest.mark.parametrize('failure', [None, 'pytest', 'backup', 'init-db', '--import-file'])
def test_migration_tests_image_before_data_changes_and_keeps_gate_closed_on_failure(project, monkeypatch, failure):
    calls, gates = [], []
    monkeypatch.setattr(deploy_release, 'ROOT', project)
    monkeypatch.setattr(deploy_release, 'plugins', lambda: {'original-plugin': 'same-id'})
    monkeypatch.setattr(deploy_release, 'health', lambda: {'8092': {'status': 'ready', 'revision': '0005_gunpla'}})
    monkeypatch.setattr(deploy_release, 'configure_audit', lambda *a, **k: None)
    monkeypatch.setattr(deploy_release, 'audit', lambda *a, **k: None)
    monkeypatch.setattr(prepare_auth, 'set_gate', lambda mode: gates.append(mode))
    def run(command, **kwargs):
        calls.append(command)
        if failure and failure in command:
            raise subprocess.CalledProcessError(1, command)
        return SimpleNamespace(returncode=0, stdout='0.11.0' if command[:3] == ['docker', 'image', 'inspect'] else '')
    monkeypatch.setattr(deploy_release.subprocess, 'run', run)
    def backup(*args):
        calls.append(['backup'])
        if failure == 'backup':
            raise RuntimeError('backup failed')
        return project / 'backups/frozen.json'
    monkeypatch.setattr(gunpla_ops, 'backup_and_freeze', backup)
    monkeypatch.setattr(gunpla_ops, 'install_timer', lambda *a: calls.append(['install_timer']))
    monkeypatch.setattr(gunpla_ops, 'account_fingerprints', lambda *a: {'production': 'unchanged'})
    monkeypatch.setattr('sys.argv', ['deploy_release', '--image', 'dual-catalog:0.11.0', '--reason', 'unit migration', '--migrate', '--import-gunpla', str(project / 'data/artifacts/gunpla-source/catalog.json')])
    if failure:
        with pytest.raises((RuntimeError, subprocess.CalledProcessError)):
            deploy_release.main()
        assert gates[-1] == 'closed' and 'open' not in gates
        assert not any('rollback' in str(c) for c in calls)
    else:
        deploy_release.main()
        assert gates == ['closed', 'open']
        at = lambda word: next(i for i, call in enumerate(calls) if word in call)
        assert at('pytest') < at('backup') < at('init-db') < at('--import-file') < at('--warm-start') < at('install_timer')
        assert sum('init-db' in c for c in calls) == 2
        imports = [c for c in calls if '--import-file' in c]
        assert len(imports) == 1 and '/app/gunpla-import.json' in imports[0]
        assert str(project / 'backups/frozen.json') + ':/app/gunpla-import.json:ro' in imports[0]


def test_old_database_revision_cannot_open_the_new_application_gate(project, monkeypatch):
    monkeypatch.setattr(prepare_auth, 'ROOT', project)
    monkeypatch.setattr(prepare_auth, 'json_get', lambda url: {'status': 'ready', 'revision': '0004_tomica_news'})
    prepare_auth.set_gate('closed')
    with pytest.raises(RuntimeError, match='readiness'):
        prepare_auth.set_gate('open')
    assert prepare_auth.gate_file().exists()


def test_backup_freezes_exact_export_and_never_puts_database_password_in_argv(project, monkeypatch):
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        if command[0].endswith('pg_dump'):
            Path(command[command.index('-f') + 1]).write_bytes(b'PGDMP synthetic backup fixture')
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(gunpla_ops.subprocess, 'run', run)
    monkeypatch.setattr(gunpla_ops.os, 'chown', lambda *a: None, raising=False)
    source = project / 'data/artifacts/gunpla-source/catalog.json'
    before = source.read_bytes()
    frozen = gunpla_ops.backup_and_freeze(project, 'dual-catalog:0.11.0', source)
    source.write_text('{}')
    assert frozen.read_bytes() == before
    pg = [c for c in calls if c[0][0].endswith('pg_dump')]
    assert len(pg) == 2 and all(c[1]['env']['PGPASSWORD'] == 'private!' for c in pg)
    assert all('private!' not in str(c[0]) and 'private%21' not in str(c[0]) for c in calls)
    sqlite = [c[0] for c in calls if '-c' in c[0]]
    assert len(sqlite) == 2 and all('--user' in c and '10001:10001' in c and 'none' in c for c in sqlite)
    assert all('source.backup(target)' in c[-1] for c in sqlite)


def test_export_outside_project_or_without_products_is_rejected(project):
    outside = project / 'other.json'; outside.write_text('{}')
    with pytest.raises(ValueError):
        gunpla_ops.backup_and_freeze(project, 'unused', outside)
    source = project / 'data/artifacts/gunpla-source/catalog.json'; source.write_text('{"schema_version":1,"entries":[]}')
    with pytest.raises(ValueError):
        gunpla_ops.backup_and_freeze(project, 'unused', source)


def test_weekly_timer_uses_current_image_and_only_owns_its_sync_container(project, tmp_path, monkeypatch):
    units = tmp_path / 'units'; units.mkdir()
    monkeypatch.setattr(gunpla_ops.subprocess, 'run', lambda *a, **k: None)
    gunpla_ops.install_timer(project, units)
    service = (units / 'dual-catalog-gunpla-sync.service').read_text()
    timer = (units / 'dual-catalog-gunpla-sync.timer').read_text()
    assert '${APP_IMAGE}' in service and '--mode incremental' in service
    assert 'OnCalendar=Sun *-*-* 03:30:00 Asia/Shanghai' in timer and 'Persistent=true' in timer
    assert 'fish-search' not in service and 'qq-summary-bot' not in service
