from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from backend.app.config import ROOT


def test_upgrade_existing_and_fresh_schema_preserves_basic_records(tmp_path):
    url = 'sqlite:///' + str(tmp_path / 'migration.db')
    config = Config(str(ROOT / 'backend/alembic.ini'))
    config.attributes['database_url'] = url
    command.upgrade(config, '0002_sync_runtime')
    engine = create_engine(url)
    assert 'pokemon_details' not in inspect(engine).get_table_names()
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO pokemon (id,dex,name_zh,types,abilities,source_url,checked_at,updated_at) VALUES ('existing',1,'妙蛙种子','[]','[]','','2026-11-10','2026-11-10')"))
    command.upgrade(config, 'head')
    assert 'pokemon_details' in inspect(engine).get_table_names()
    with engine.connect() as connection:
        assert connection.scalar(text('SELECT name_zh FROM pokemon WHERE dex=1')) == '妙蛙种子'
    command.downgrade(config, '0002_sync_runtime')
    assert 'pokemon_details' not in inspect(engine).get_table_names()
    command.upgrade(config, 'head')
    with engine.connect() as connection:
        assert connection.scalar(text('SELECT count(*) FROM pokemon')) == 1
    engine.dispose()


def test_news_upgrade_and_downgrade_preserve_existing_catalogs(tmp_path):
    from sqlalchemy.orm import Session
    from backend.app.models import Pokemon, TomicaModel
    config = Config(str(ROOT / 'backend/alembic.ini'))
    url = 'sqlite:///' + str(tmp_path / 'news-migration.db')
    config.attributes['database_url'] = url
    command.upgrade(config, '0003_pokemon_details')
    engine = create_engine(url)
    assert 'tomica_news' not in inspect(engine).get_table_names()
    with Session(engine) as session:
        session.add_all([Pokemon(dex=1, name_zh='妙蛙种子'), TomicaModel(number='114', name_original='existing car')])
        session.commit()
    command.upgrade(config, 'head')
    assert 'tomica_news' in inspect(engine).get_table_names()
    command.downgrade(config, '0003_pokemon_details')
    assert 'tomica_news' not in inspect(engine).get_table_names()
    command.upgrade(config, 'head')
    with engine.connect() as connection:
        assert connection.scalar(text('SELECT name_zh FROM pokemon WHERE dex=1')) == '妙蛙种子'
        assert connection.scalar(text("SELECT name_original FROM tomica_models WHERE number='114'")) == 'existing car'
    engine.dispose()


def test_gunpla_migration_only_adds_its_table_and_preserves_catalogs(tmp_path):
    config = Config(str(ROOT / 'backend/alembic.ini'))
    config.attributes['database_url'] = 'sqlite:///' + str(tmp_path / 'gunpla-migration.db')
    command.upgrade(config, '0004_tomica_news')
    engine = create_engine(config.attributes['database_url'])
    assert 'gunpla_entries' not in inspect(engine).get_table_names()
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO pokemon (id,dex,name_zh,types,abilities,source_url,checked_at,updated_at) VALUES ('retained',1,'retained','[]','[]','','2026-11-11','2026-11-11')"))
    command.upgrade(config, 'head')
    assert 'gunpla_entries' in inspect(engine).get_table_names()
    with engine.connect() as connection:
        assert connection.scalar(text('SELECT version_num FROM alembic_version')) == '0005_gunpla'
    command.downgrade(config, '0004_tomica_news')
    assert 'gunpla_entries' not in inspect(engine).get_table_names()
    with engine.connect() as connection:
        assert connection.scalar(text('SELECT name_zh FROM pokemon WHERE dex=1')) == 'retained'
    command.upgrade(config, 'head')
    engine.dispose()
