from alembic import op
import sqlalchemy as sa

revision = '0004_tomica_news'
down_revision = '0003_pokemon_details'


def upgrade():
    op.create_table('tomica_news',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('checked_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('slug', sa.String(80), nullable=False),
        sa.Column('archive_month', sa.String(7), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('source_name', sa.String(), nullable=False),
        sa.Column('source_url', sa.Text(), nullable=False),
        sa.Column('content_hash', sa.String(64), nullable=False),
        sa.Column('data', sa.JSON(), nullable=False))
    op.create_index('ix_tomica_news_slug', 'tomica_news', ['slug'], unique=True)
    op.create_index('ix_tomica_news_archive_month', 'tomica_news', ['archive_month'])


def downgrade():
    op.drop_table('tomica_news')
