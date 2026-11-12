from types import SimpleNamespace
import subprocess

import pytest
from scripts import deploy_release


def test_removed_optional_projects_do_not_block_catalog_deploy(monkeypatch):
    def run(args, **kwargs):
        assert args == ['docker', 'ps', '-a', '--format', '{{.Names}}']
        return SimpleNamespace(stdout='dual-catalog-api-1\ndual-catalog-preview-proxy\n')
    monkeypatch.setattr(deploy_release.subprocess, 'run', run)
    assert deploy_release.plugins() == {}


def test_existing_optional_container_identity_remains_guarded(monkeypatch):
    current = {'nginx': 'original-container'}
    def run(args, **kwargs):
        if args[1] == 'ps':
            return SimpleNamespace(stdout='dual-catalog-api-1\n' + '\n'.join(current))
        return SimpleNamespace(stdout=current[args[-1]])
    monkeypatch.setattr(deploy_release.subprocess, 'run', run)
    before = deploy_release.plugins()
    current['nginx'] = 'unexpected-replacement'
    assert before == {'nginx': 'original-container'} and before != deploy_release.plugins()
    current.clear()
    assert deploy_release.plugins() == {}


@pytest.mark.parametrize('fail_on', ['ps', 'inspect'])
def test_engine_or_discovery_race_failure_is_not_hidden(monkeypatch, fail_on):
    def run(args, **kwargs):
        if args[1] == fail_on:
            raise subprocess.CalledProcessError(1, args)
        return SimpleNamespace(stdout='nginx\n')
    monkeypatch.setattr(deploy_release.subprocess, 'run', run)
    with pytest.raises(subprocess.CalledProcessError):
        deploy_release.plugins()
