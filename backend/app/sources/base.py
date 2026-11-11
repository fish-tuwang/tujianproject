from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol
from backend.app.schemas import ParsedPage


class SourceParseError(ValueError):
    pass


@dataclass
class FetchResult:
    url: str
    final_url: str = ''
    status: int = 0
    headers: dict = field(default_factory=dict)
    body: bytes = b''
    etag: str | None = None
    last_modified: str | None = None
    content_hash: str = ''
    not_modified: bool = False
    checked_at: datetime | None = None
    error: str | None = None
    retry_after: float = 0


class SourceAdapter(Protocol):
    def seed_urls(self) -> list[str]: ...
    def discover(self, url: str, body: bytes) -> list[str]: ...
    def parse(self, url: str, body: bytes) -> ParsedPage: ...
