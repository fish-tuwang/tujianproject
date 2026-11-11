import gzip
import json
import logging
import os
from pathlib import Path

import pytest
from sqlalchemy import select

from backend.app.audit import audit, configure_audit
from backend.app.models import TomicaModel
from backend.app.repository import CatalogError, CatalogRepository
from backend.tests.test_repository import car
from backend.tests.test_sync import Client, setup
from scripts.view_logs import main as view_logs, records


@pytest.fixture
def audit_directory(tmp_path):
    logger = logging.getLogger('catalog.audit.collection')
    handlers, level, propagate = logger.handlers[:], logger.level, logger.propagate
    logger.handlers = []
    configure_audit(tmp_path, channels={'collection'})
    yield tmp_path
    for handler in logger.handlers:
        handler.close()
    logger.handlers, logger.level, logger.propagate = handlers, level, propagate


def test_unicode_stays_in_one_json_line(audit_directory):
    path = audit_directory / 'collection.jsonl'
    audit('record_created', name='植木屋さん\n"卡车"', fields=['name_original'])
    lines = path.read_text(encoding='utf-8').splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])['name'] == '植木屋さん\n"卡车"'
    assert json.loads(lines[0])['time'].endswith('+00:00')


@pytest.mark.skipif(os.name == 'nt', reason='server rotation requires POSIX rename of an open log file')
def test_external_rotation_reopens_new_log(audit_directory):
    path = audit_directory / 'collection.jsonl'
    audit('record_created', name='卡车')
    previous = path.with_suffix('.jsonl.1')
    path.rename(previous)
    path.touch()
    audit('run_finished', status='succeeded')
    assert json.loads(path.read_text(encoding='utf-8'))['event'] == 'run_finished'
    assert json.loads(previous.read_text(encoding='utf-8'))['event'] == 'record_created'


def test_candidate_changes_distinguish_insert_update_and_unchanged(session):
    repo, changes = CatalogRepository(session), []
    repo.publish_candidates(None, [car('001-1', 2020)], changes=changes)
    session.commit()
    assert [(r['action'], r['name']) for r in changes] == [('created', '001-1')]
    changes.clear()
    repo.publish_candidates(None, [car('001-1', 2020)], changes=changes)
    assert changes == []
    repo.publish_candidates(None, [car('001-1', 2021)], changes=changes)
    assert changes[0]['action'] == 'updated'
    assert changes[0]['fields'] == ['release_year']


def test_sync_records_changes_only_after_page_commit(session, monkeypatch):
    captured = []
    service, factory = setup(session, Client())

    def collect(event, **fields):
        if event == 'record_created' and fields['kind'] == 'tomica_model':
            with factory() as check:
                assert check.get(TomicaModel, fields['entity_id']) is not None
        captured.append((event, fields))

    monkeypatch.setattr('backend.app.sync.service.audit', collect)
    run_id = service.enqueue_run('tomica', 'full', limit=2)
    session.commit()
    result = service.run_once(run_id)
    rows = [data for event, data in captured if event == 'record_created']
    assert rows and all(row['name'] and row['source'] == 'tomica' for row in rows)
    assert result.counts['created'] == len(rows)
    assert captured[0][0] == 'run_started' and captured[-1][0] == 'run_finished'
    assert len([event for event, _ in captured if event == 'page_checked']) == 2


def test_rolled_back_page_never_logs_committed_new_records(session, monkeypatch):
    captured = []
    service, _ = setup(session, Client())
    original = CatalogRepository.publish_candidates

    def fail_after_write(self, *args, **kwargs):
        original(self, *args, **kwargs)
        raise CatalogError('TEST_ISOLATION', 'transaction rolls back')

    monkeypatch.setattr(CatalogRepository, 'publish_candidates', fail_after_write)
    monkeypatch.setattr('backend.app.sync.service.audit', lambda event, **fields: captured.append((event, fields)))
    run_id = service.enqueue_run('tomica', 'full', limit=1)
    session.commit()
    assert service.run_once(run_id).status == 'partial'
    assert not any(event.startswith('record_') for event, _ in captured)
    assert any(event == 'page_failed' and row['code'] == 'TEST_ISOLATION' for event, row in captured)
    session.expire_all()
    assert session.scalar(select(TomicaModel)) is None


def test_query_reads_compressed_history_and_filters_ips(tmp_path, monkeypatch, capsys):
    old = {'time': '2026-11-09T16:01:00+00:00', 'client_ip': '203.0.113.1', 'status': 200}
    with gzip.open(tmp_path / 'access.jsonl.2.gz', 'wt', encoding='utf-8') as stream:
        stream.write(json.dumps(old) + '\n')
    (tmp_path / 'access.jsonl').write_text(json.dumps({**old, 'client_ip': '203.0.113.2', 'status': 404}) + '\n', encoding='utf-8')
    assert len(list(records(tmp_path, 'access'))) == 2
    monkeypatch.setattr('sys.argv', ['view_logs', 'access', '--directory', str(tmp_path), '--since', '2026-11-10', '--summary'])
    view_logs()
    output = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert len(output) == 2 and sum(row['requests'] for row in output) == 2
    assert sum(row['errors'] for row in output) == 1
    monkeypatch.setattr('sys.argv', ['view_logs', 'access', '--directory', str(tmp_path), '--ip', '203.0.113.1'])
    view_logs()
    assert json.loads(capsys.readouterr().out)['client_ip'] == '203.0.113.1'


def test_news_import_change_labels(session):
    from scripts.seed_tomica_news import import_articles, load_articles
    directory = Path(__file__).resolve().parents[1] / 'data/tomica-news'
    changes = []
    articles = load_articles(directory)
    import_articles(session, articles, changes=changes)
    session.commit()
    assert changes[0]['action'] == 'created' and changes[0]['month'] == '2026-11'
    changes.clear()
    import_articles(session, articles, changes=changes)
    assert changes == []


def test_failed_release_restores_environment_and_audits_rollback(tmp_path, monkeypatch):
    import subprocess
    from types import SimpleNamespace
    from scripts import deploy_release
    originals = {'.env': 'APP_IMAGE=dual-catalog:0.6.3\nSECRET=do-not-log-this\n', '.env.demo': 'APP_IMAGE=dual-catalog:0.6.3\nSECRET=private-demo\n'}
    for name, content in originals.items():
        (tmp_path / name).write_text(content)
    for name in ['Dockerfile.release', 'backend/app/audit.py', 'backend/app/repository.py', 'backend/app/sync/service.py', 'backend/app/worker.py', 'deploy/preview-nginx.conf', 'backend/app/auth_store.py', 'backend/app/auth.py', 'backend/app/auth_cli.py', 'backend/app/gunpla.py', 'backend/app/sources/gunpla.py', 'backend/migrations/versions/0005_gunpla.py']:
        target = tmp_path / 'app' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('source')
    captured = []
    monkeypatch.setattr(deploy_release, 'ROOT', tmp_path)
    monkeypatch.setattr(deploy_release, 'plugins', lambda: {'unchanged': 'container-id'})
    monkeypatch.setattr(deploy_release, 'health', lambda: {'8092': {'status': 'ready'}})
    monkeypatch.setattr(deploy_release, 'configure_audit', lambda *a, **k: None)
    monkeypatch.setattr(deploy_release, 'audit', lambda event, **fields: captured.append({'event': event, **fields}))

    def execute(args, **kwargs):
        if args[:2] == ['docker', 'build']:
            raise subprocess.CalledProcessError(1, args)
        return SimpleNamespace(returncode=0, stdout='')

    monkeypatch.setattr(deploy_release.subprocess, 'run', execute)
    monkeypatch.setattr('sys.argv', ['deploy_release', '--image', 'dual-catalog:0.7.0', '--reason', 'test failure'])
    with pytest.raises(subprocess.CalledProcessError):
        deploy_release.main()
    assert all((tmp_path / name).read_text() == content for name, content in originals.items())
    assert {'deployment_failed', 'rollback_started', 'rollback_finished'} <= {r['event'] for r in captured}
    assert not any(r['event'] == 'deployment_finished' for r in captured)
    assert 'do-not-log-this' not in json.dumps(captured) and 'private-demo' not in json.dumps(captured)
