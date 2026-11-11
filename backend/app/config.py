from pathlib import Path
from urllib.parse import urlsplit

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / '.env', extra='ignore')
    database_url: str = 'postgresql+psycopg://dual_catalog_app@127.0.0.1:15432/dual_catalog_demo'
    admin_token: SecretStr = SecretStr('')
    source_interval_seconds: float = 2
    timezone: str = 'Asia/Shanghai'
    object_store_endpoint: str = ''
    object_store_bucket: str = ''
    object_store_access_key: SecretStr = SecretStr('')
    object_store_secret_key: SecretStr = SecretStr('')
    public_image_base_url: str = ''
    artifact_dir: str = 'artifacts/acceptance'
    redis_url: SecretStr = SecretStr('')
    cache_namespace: str = 'dual-catalog:v2'
    auth_enabled: bool = True
    auth_store_path: str = 'artifacts/auth/accounts.sqlite3'
    auth_cookie_secure: bool = True
    auth_session_seconds: int = 43200
    auth_service_token: SecretStr = SecretStr('')

    @field_validator('auth_session_seconds')
    @classmethod
    def validate_session_seconds(cls, value):
        if not 60 <= value <= 604800:
            raise ValueError('session lifetime must be between 60 seconds and 7 days')
        return value

    @property
    def auth_path(self):
        path = Path(self.auth_store_path)
        return path if path.is_absolute() else ROOT / path

    @field_validator('source_interval_seconds')
    @classmethod
    def validate_interval(cls, value):
        if value < 2:
            raise ValueError('source interval must be at least 2 seconds')
        return value

    @field_validator('database_url')
    @classmethod
    def validate_database(cls, value):
        if not urlsplit(value).scheme.startswith(('postgresql', 'sqlite')):
            raise ValueError('unsupported database URL')
        return value

    @property
    def admin_enabled(self):
        return bool(self.admin_token.get_secret_value())
