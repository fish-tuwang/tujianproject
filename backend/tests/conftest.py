import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


@pytest.fixture
def session():
    from backend.app.models import Base
    engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
    event.listen(engine, 'connect', lambda db, _: db.execute('PRAGMA foreign_keys=ON'))
    Base.metadata.create_all(engine)
    with Session(engine) as value:
        yield value
    engine.dispose()
