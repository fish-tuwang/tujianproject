from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now():
    return datetime.now(timezone.utc)


def uid():
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class Record:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class TomicaModel(Record, Base):
    __tablename__ = 'tomica_models'
    series: Mapped[str] = mapped_column(default='Tomica')
    number: Mapped[str] = mapped_column(index=True)
    generation: Mapped[str] = mapped_column(default='')
    name_original: Mapped[str]
    name_display: Mapped[str | None]
    brand: Mapped[str | None] = mapped_column(index=True)
    release_year: Mapped[int | None] = mapped_column(index=True)
    release_month: Mapped[int | None]
    scale: Mapped[str | None]
    source_url: Mapped[str] = mapped_column(Text, default='')
    source_locator: Mapped[str] = mapped_column(default='')
    primary_image_id: Mapped[str | None]
    __table_args__ = (CheckConstraint('release_month IS NULL OR release_month BETWEEN 1 AND 12'),)


class TomicaNews(Record, Base):
    __tablename__ = 'tomica_news'
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    archive_month: Mapped[str] = mapped_column(String(7), index=True)
    title: Mapped[str] = mapped_column(Text)
    source_name: Mapped[str]
    source_url: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    data: Mapped[dict] = mapped_column(JSON)


class GunplaEntry(Record, Base):
    __tablename__ = 'gunpla_entries'
    kind: Mapped[str] = mapped_column(String(20), index=True)
    source_key: Mapped[str] = mapped_column(String(120))
    name: Mapped[str] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    content_hash: Mapped[str] = mapped_column(String(64))
    __table_args__ = (UniqueConstraint('kind', 'source_key'),)


class TomicaVariant(Record, Base):
    __tablename__ = 'tomica_variants'
    model_id: Mapped[str] = mapped_column(ForeignKey('tomica_models.id'), index=True)
    variant_code: Mapped[str | None]
    description: Mapped[str] = mapped_column(Text, default='')
    special_orderer: Mapped[str | None]
    country: Mapped[str | None]
    release_year: Mapped[int | None]
    release_month: Mapped[int | None]
    image_id: Mapped[str | None]
    source_url: Mapped[str] = mapped_column(Text, default='')
    __table_args__ = (CheckConstraint('release_month IS NULL OR release_month BETWEEN 1 AND 12'),)


class Pokemon(Record, Base):
    __tablename__ = 'pokemon'
    dex: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    name_zh: Mapped[str]
    name_ja: Mapped[str | None]
    name_en: Mapped[str | None]
    types: Mapped[list] = mapped_column(JSON, default=list)
    height_m: Mapped[float | None] = mapped_column(Float)
    weight_kg: Mapped[float | None] = mapped_column(Float)
    abilities: Mapped[list] = mapped_column(JSON, default=list)
    source_url: Mapped[str] = mapped_column(Text, default='')
    primary_image_id: Mapped[str | None]
    __table_args__ = (CheckConstraint('dex > 0'),)


class PokemonDetail(Record, Base):
    __tablename__ = 'pokemon_details'
    dex: Mapped[int] = mapped_column(ForeignKey('pokemon.dex'), unique=True, index=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    source_url: Mapped[str] = mapped_column(Text, default='')


class PokemonForm(Record, Base):
    __tablename__ = 'pokemon_forms'
    dex: Mapped[int] = mapped_column(ForeignKey('pokemon.dex'), index=True)
    form_key: Mapped[str]
    display_name: Mapped[str]
    types: Mapped[list] = mapped_column(JSON, default=list)
    image_id: Mapped[str | None]
    differences: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (UniqueConstraint('dex', 'form_key'),)


class Evolution(Record, Base):
    __tablename__ = 'evolutions'
    relation_key: Mapped[str] = mapped_column(unique=True)
    from_dex: Mapped[int] = mapped_column(index=True)
    to_dex: Mapped[int]
    from_form: Mapped[str] = mapped_column(default='default')
    to_form: Mapped[str] = mapped_column(default='default')
    condition: Mapped[str] = mapped_column(Text, default='')


class SourcePage(Record, Base):
    __tablename__ = 'source_pages'
    source: Mapped[str]
    url: Mapped[str] = mapped_column(Text)
    etag: Mapped[str | None]
    last_modified: Mapped[str | None]
    content_hash: Mapped[str] = mapped_column(default='')
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    discovered_urls: Mapped[list] = mapped_column(JSON, default=list)
    accepted_count: Mapped[int] = mapped_column(default=0)
    __table_args__ = (UniqueConstraint('source', 'url'),)


class SourceIdentity(Record, Base):
    __tablename__ = 'source_identities'
    source: Mapped[str]
    kind: Mapped[str]
    source_key: Mapped[str] = mapped_column(Text)
    entity_id: Mapped[str]
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (UniqueConstraint('source', 'kind', 'source_key'),)


class SyncRun(Record, Base):
    __tablename__ = 'sync_runs'
    source: Mapped[str] = mapped_column(index=True)
    mode: Mapped[str] = mapped_column(default='incremental')
    status: Mapped[str] = mapped_column(default='queued', index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
    limit: Mapped[int | None]
    replay_of: Mapped[str | None]
    followup_mode: Mapped[str | None]
    last_error: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (Index('uq_active_source', 'source', unique=True, postgresql_where=text("status IN ('queued','running')"), sqlite_where=text("status IN ('queued','running')")),)


class SyncItem(Record, Base):
    __tablename__ = 'sync_items'
    run_id: Mapped[str] = mapped_column(ForeignKey('sync_runs.id'), index=True)
    url: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(default='pending')
    attempts: Mapped[int] = mapped_column(default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    candidates: Mapped[list] = mapped_column(JSON, default=list)
    issues: Mapped[list] = mapped_column(JSON, default=list)
    __table_args__ = (UniqueConstraint('run_id', 'url'),)


class FieldOverride(Record, Base):
    __tablename__ = 'field_overrides'
    kind: Mapped[str]
    entity_key: Mapped[str]
    field: Mapped[str]
    value: Mapped[object] = mapped_column(JSON, nullable=True)
    actor: Mapped[str]
    __table_args__ = (UniqueConstraint('kind', 'entity_key', 'field'),)


class ImageAsset(Record, Base):
    __tablename__ = 'image_assets'
    source_url: Mapped[str] = mapped_column(Text, unique=True)
    content_hash: Mapped[str | None]
    object_key: Mapped[str | None]
    rights_reference: Mapped[str | None]
    attribution: Mapped[str | None]
    status: Mapped[str] = mapped_column(default='pending')
    last_error: Mapped[str | None] = mapped_column(Text)
    rights_status: Mapped[str] = mapped_column(default='pending')
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(default=0)
    public_url: Mapped[str | None]


class CatalogRevision(Base):
    __tablename__ = 'catalog_revisions'
    source: Mapped[str] = mapped_column(primary_key=True)
    revision: Mapped[int] = mapped_column(default=0)
