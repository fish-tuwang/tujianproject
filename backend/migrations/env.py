from alembic import context
from sqlalchemy import create_engine
from backend.app.config import Settings
from backend.app.models import Base

config = context.config
target_metadata = Base.metadata
url = config.attributes.get('database_url') or Settings().database_url
if context.is_offline_mode():
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
