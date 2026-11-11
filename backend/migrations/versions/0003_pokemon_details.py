from alembic import op
import sqlalchemy as sa

revision = '0003_pokemon_details'
down_revision = '0002_sync_runtime'


def upgrade():
    op.create_table('pokemon_details',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('checked_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('dex', sa.Integer(), sa.ForeignKey('pokemon.dex'), nullable=False),
        sa.Column('data', sa.JSON(), nullable=False),
        sa.Column('source_url', sa.Text(), nullable=False))
    op.create_index('ix_pokemon_details_dex', 'pokemon_details', ['dex'], unique=True)


def downgrade():
    op.drop_table('pokemon_details')
