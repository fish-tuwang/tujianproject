from alembic import op
import sqlalchemy as sa

revision = '0005_gunpla'
down_revision = '0004_tomica_news'


def upgrade():
    op.create_table('gunpla_entries',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('checked_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('kind', sa.String(20), nullable=False),
        sa.Column('source_key', sa.String(120), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('data', sa.JSON(), nullable=False),
        sa.Column('content_hash', sa.String(64), nullable=False),
        sa.UniqueConstraint('kind', 'source_key'))
    op.create_index('ix_gunpla_entries_kind', 'gunpla_entries', ['kind'])


def downgrade():
    op.drop_table('gunpla_entries')
