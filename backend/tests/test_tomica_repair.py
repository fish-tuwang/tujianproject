import hashlib
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from backend.app.config import Settings
from backend.app.models import Base, FieldOverride, ImageAsset, SourceIdentity, SourcePage, SyncRun, TomicaModel, TomicaVariant
from backend.app.sources.base import FetchResult
from backend.app.sources.tomica import BASE
from scripts import repair_tomica_editions as repair


@pytest.fixture
def caption_repair(tmp_path, monkeypatch):
    engine = create_engine('sqlite:///' + str(tmp_path / 'repair.db'))
    event.listen(engine, 'connect', lambda connection, _: connection.execute('PRAGMA foreign_keys=ON'))
    Base.metadata.create_all(engine)
    url = BASE + 'special/utf8.html'
    ids = {}
    with Session(engine) as session, session.begin():
        for label, name, photo, group in [('readable', '繝代Φ', 'bread.jpg', ''), ('unlabelled', '裏板変更', 'one.jpg', '裏板変更')]:
            image_url = BASE + 'special/' + photo
            digest = hashlib.sha256(image_url.encode()).hexdigest()
            key = 'edition:' + digest[:32]
            image = ImageAsset(source_url=image_url)
            session.add(image)
            session.flush()
            model = TomicaModel(number='SP', name_original=name, source_url=url, source_locator=key, primary_image_id=image.id)
            session.add(model)
            session.flush()
            variant = TomicaVariant(model_id=model.id, image_id=image.id, source_url=url, description=name)
            session.add(variant)
            session.flush()
            session.add_all([
                SourceIdentity(source='tomica', kind='tomica_model', source_key=key, entity_id=model.id, evidence={'url': url, 'caption': name, 'group': group, 'description': '', 'image_urls': [image_url]}),
                SourceIdentity(source='tomica', kind='tomica_variant', source_key=key + ':' + digest[:24], entity_id=variant.id, evidence={'url': url, 'model_key': key, 'image_url': image_url}),
            ])
            ids[label] = model.id
        base = TomicaModel(number='001', name_original='ブルーバード', source_locator='001-1')
        session.add(base)
        session.add(SourcePage(source='tomica', url=url, accepted_count=4))
        session.flush()
        ids['base'] = base.id
    body = '<meta charset="Shift_JIS"><title>collection 特注</title><table><tr><td>パンどろぼう</td></tr><tr><td><img src="bread.jpg"></td></tr></table><table><tr><td colspan="3">裏板変更</td></tr><tr><td><img src="one.jpg"></td><td><img src="two.jpg"></td></tr></table>'.encode('utf-8')
    output = tmp_path / 'acceptance'
    output.mkdir()
    settings = Settings(database_url=str(engine.url), artifact_dir=str(output))
    connection = engine.connect()
    lease = SimpleNamespace(connection=connection, assert_alive=lambda: None, close=connection.close)
    monkeypatch.setattr(repair, 'Settings', lambda: settings)
    monkeypatch.setattr(repair, 'create_engine', lambda *a, **kw: engine)
    monkeypatch.setattr(repair, 'SourceLockProvider', lambda e: SimpleNamespace(acquire=lambda source: lease))
    monkeypatch.setattr(repair, 'SourceHttpClient', lambda *a, **kw: SimpleNamespace(fetch=lambda u: FetchResult(url=u, body=body, status=200, content_hash=hashlib.sha256(body).hexdigest()), close=lambda: None))
    monkeypatch.setattr(repair, 'configure_audit', lambda *a, **kw: None)
    monkeypatch.setattr(repair, 'audit', lambda *a, **kw: None)
    monkeypatch.setattr('sys.argv', ['repair', '--apply'])
    return engine, ids, output


def test_verified_repair_preserves_base_ids_and_cached_assets(caption_repair):
    engine, ids, output = caption_repair
    repair.main()
    with Session(engine) as session:
        assert session.get(TomicaModel, ids['readable']).name_original.startswith('パンどろぼう')
        assert session.get(TomicaModel, ids['base']).name_original == 'ブルーバード'
        assert session.get(TomicaModel, ids['unlabelled']) is None
        assert session.scalar(select(func.count()).select_from(TomicaModel)) == 2
        assert session.scalar(select(func.count()).select_from(TomicaVariant)) == 1
        assert session.scalar(select(func.count()).select_from(ImageAsset)) == 2
        assert session.scalar(select(SourcePage)).accepted_count == 2
    receipt = json.loads((output / 'edition-caption-repair.json').read_text(encoding='utf-8'))
    assert receipt['status'] == 'pass' and receipt['remaining_suspect_pages'] == []
    assert receipt['removed_models'][0]['model']['id'] == ids['unlabelled']


def test_manual_correction_stops_unlabelled_edition_deletion(caption_repair):
    engine, ids, _ = caption_repair
    with Session(engine) as session, session.begin():
        session.add(FieldOverride(kind='tomica_model', entity_key=ids['unlabelled'], field='name_display', value='人工核对名称', actor='user'))
    with pytest.raises(RuntimeError, match='manual correction found'):
        repair.main()
    with Session(engine) as session:
        assert session.get(TomicaModel, ids['unlabelled']) is not None
        assert session.get(TomicaModel, ids['base']) is not None
        assert session.scalar(select(SyncRun)).status == 'failed'
