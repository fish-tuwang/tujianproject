import pytest
from pydantic import ValidationError
from backend.app.config import Settings


def test_environment(monkeypatch):
    monkeypatch.setenv('TIMEZONE', 'UTC')
    assert Settings(_env_file=None).timezone == 'UTC'


@pytest.mark.parametrize('values', [{'source_interval_seconds': 1}, {'database_url': 'bad'}])
def test_invalid(values):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)


def test_secret_and_disabled():
    config = Settings(_env_file=None, admin_token='never-display-this-token')
    assert 'never-display-this-token' not in repr(config)
    assert not Settings(_env_file=None, admin_token='').admin_enabled
