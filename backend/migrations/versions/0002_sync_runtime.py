from alembic import op
import sqlalchemy as sa

revision = '0002_sync_runtime'
down_revision = '0001_catalog'


def upgrade():
    for table, columns in {
        'source_pages': [sa.Column('discovered_urls', sa.JSON(), nullable=False, server_default='[]'), sa.Column('accepted_count', sa.Integer(), nullable=False, server_default='0')],
        'sync_runs': [sa.Column('limit', sa.Integer()), sa.Column('replay_of', sa.String(36)), sa.Column('followup_mode', sa.String()), sa.Column('last_error', sa.Text())],
        'image_assets': [sa.Column('rights_status', sa.String(), nullable=False, server_default='pending'), sa.Column('next_retry_at', sa.DateTime(timezone=True)), sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'), sa.Column('public_url', sa.String())],
    }.items():
        for column in columns:
            op.add_column(table, column)
    op.create_index('uq_active_source', 'sync_runs', ['source'], unique=True, postgresql_where=sa.text("status IN ('queued','running')"), sqlite_where=sa.text("status IN ('queued','running')"))


def downgrade():
    op.drop_index('uq_active_source', table_name='sync_runs')
    for table, columns in {'source_pages': ['discovered_urls', 'accepted_count'], 'sync_runs': ['limit', 'replay_of', 'followup_mode', 'last_error'], 'image_assets': ['rights_status', 'next_retry_at', 'attempts', 'public_url']}.items():
        for name in reversed(columns):
            op.drop_column(table, name)
