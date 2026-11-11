import pytest
from sqlalchemy import event, select

from backend.app.models import ImageAsset, Pokemon, TomicaModel
from backend.app.repository import CatalogRepository
from backend.app.schemas import SourceCandidate


@pytest.mark.parametrize('source,kind,model', [('tomica', 'tomica_model', TomicaModel), ('pokemon', 'pokemon', Pokemon)])
def test_bulk_snapshot_has_bounded_queries_and_preserves_effective_fields(session, source, kind, model):
    images = [ImageAsset(source_url=f'http://tomica.minibird.jp/t-tomica/jpg/car photo {index}.jpg', attribution='source attribution ' + str(index)) for index in range(3)]
    session.add_all(images)
    session.flush()
    repo = CatalogRepository(session)
    for number in range(1, 7):
        fields = {'number': str(number), 'name_original': '原名' + str(number)} if source == 'tomica' else {'dex': number, 'name_zh': '原名' + str(number)}
        repo.publish_candidates(None, [SourceCandidate(kind=kind, source_key=str(number), fields={**fields, 'primary_image_id': images[(number - 1) % 3].id})], source=source)
    first = session.scalar(select(model))
    key = first.id if source == 'tomica' else str(first.dex)
    repo.set_override(kind, key, 'name_display' if source == 'tomica' else 'name_zh', '人工名称')
    session.flush()
    session.expunge_all()
    statements = []
    def count(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith('SELECT'):
            statements.append(statement)
    event.listen(session.bind, 'before_cursor_execute', count)
    try:
        rows = repo.catalog_rows(source)
    finally:
        event.remove(session.bind, 'before_cursor_execute', count)
    assert len(rows) == 6
    assert len(statements) <= 4  # Models, all overrides, and all image metadata.
    assert any(row.get('name_display') == '人工名称' or row.get('name_zh') == '人工名称' for row in rows)
    assert all(row['source_image_url'].endswith('car%20photo%20' + str((int(row.get('number') or row['dex']) - 1) % 3) + '.jpg') for row in rows)
    for row in rows:
        assert row == repo.effective(session.get(model, row['id']), kind)
