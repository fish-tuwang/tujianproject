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
