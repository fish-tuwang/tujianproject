from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

KINDS = Literal['tomica_model', 'tomica_variant', 'pokemon', 'pokemon_form', 'pokemon_detail', 'evolution']
TYPES = ['一般', '火', '水', '电', '草', '冰', '格斗', '毒', '地面', '飞行', '超能力', '虫', '岩石', '幽灵', '龙', '恶', '钢', '妖精']


class ParseIssue(BaseModel):
    code: str
    message: str
    url: str = ''
    locator: str = ''
    severity: str = 'warning'


class SourceCandidate(BaseModel):
    kind: KINDS
    source_key: str | None
    fields: dict[str, Any]
    evidence: dict[str, Any] = Field(default_factory=dict)


class ParsedPage(BaseModel):
    source: str
    url: str
    discovered_urls: list[str] = Field(default_factory=list)
    candidates: list[SourceCandidate] = Field(default_factory=list)
    issues: list[ParseIssue] = Field(default_factory=list)
    content_hash: str = ''


class ErrorResponse(BaseModel):
    code: str
    message: str


class PageResponse(BaseModel):
    items: list[dict]
    next_cursor: str | None


class Query(BaseModel):
    q: str | None = Field(default=None, max_length=100)
    limit: int = Field(default=30, ge=1, le=100)
    cursor: str | None = None

    @field_validator('q', mode='before')
    @classmethod
    def strip_query(cls, value):
        return str(value).strip() or None if value is not None else None


class TomicaQuery(Query):
    page: int | None = Field(default=None, ge=1)
    brand: str | None = None
    year: int | Literal['unknown'] | None = None

    @model_validator(mode='after')
    def distinct_pagination(self):
        if self.page is not None and self.cursor:
            raise ValueError('page and cursor cannot be combined')
        return self

    @field_validator('year')
    @classmethod
    def valid_year(cls, value):
        if isinstance(value, int) and value < 1:
            raise ValueError('year must be positive')
        return value


class PokemonQuery(Query):
    type: str | None = None
    region: str | None = None

    @field_validator('region', mode='before')
    @classmethod
    def valid_region(cls, value):
        from .pokemon_regions import SUPPORTED_REGIONS
        value = str(value).strip().lower() if value is not None else ''
        if value and value not in SUPPORTED_REGIONS:
            raise ValueError('unknown region')
        return value or None

    @field_validator('type')
    @classmethod
    def valid_type(cls, value):
        if value and value not in TYPES:
            raise ValueError('unknown type')
        return value or None


class SyncRequest(BaseModel):
    source: Literal['tomica', 'pokemon']
    mode: Literal['incremental', 'full'] = 'incremental'


class OverrideRequest(BaseModel):
    kind: KINDS
    entity_key: str
    field: str
    value: Any
