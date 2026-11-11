from alembic import op
from sqlalchemy import MetaData
from backend.app.models import Base

revision = '0001_catalog'
down_revision = None


def upgrade():
    # 初始迁移固定排除后续版本新增列；不能把当前ORM的后续结构提前创建。
    excluded = {'source_pages': {'discovered_urls', 'accepted_count'}, 'sync_runs': {'limit', 'replay_of', 'followup_mode', 'last_error'}, 'image_assets': {'rights_status', 'next_retry_at', 'attempts', 'public_url'}}
    metadata = MetaData()
    for original in Base.metadata.sorted_tables:
        if original.name in {'pokemon_details', 'tomica_news', 'gunpla_entries'}:
            continue
        table = original.to_metadata(metadata)
        for name in excluded.get(table.name, set()):
            table._columns.remove(table.c[name])
        for index in list(table.indexes):
            if index.name == 'uq_active_source':
                table.indexes.remove(index)
    metadata.create_all(op.get_bind())


def downgrade():
    Base.metadata.drop_all(op.get_bind())
