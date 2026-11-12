from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path

from PIL import Image
import pytest

from backend.app.cache import CatalogCache
from backend.app.gunpla_images import display_preview
from backend.app import gunpla_images
from backend.app.models import ImageAsset
from backend.app.reference_images import reference_path
from backend.tests.test_api import client
from backend.tests.test_auth import auth_client, signin, CLIENT
from backend.tests.test_cache import MemoryRedis


def original(color='red', mode='RGB'):
    output = BytesIO()
    Image.new(mode, (2000, 1000), color).save(output, format='PNG')
    return output.getvalue()


def seed_image(session, directory, host='staticcdn.bandaihobbysite.cn'):
    row = ImageAsset(source_url='https://' + host + '/www/uploads/fixture.png')
    session.add(row); session.commit()
    folder = directory / 'reference-images'; folder.mkdir(parents=True, exist_ok=True)
    path = reference_path(row.id, row.source_url, folder)
    path.write_bytes(original())
    return row.id, path


def test_display_keeps_aspect_and_original_bytes_and_reuses_file(tmp_path, monkeypatch):
    raw = original()
    preview = display_preview(raw, 480, tmp_path)
    with Image.open(BytesIO(preview)) as image:
        assert image.format == 'WEBP' and image.size == (480, 240)
    assert raw == original() and len(preview) < len(raw)
    files = list(tmp_path.iterdir()); stamp = files[0].stat().st_mtime_ns
    monkeypatch.setattr(Image, 'open', lambda *_: pytest.fail('cached display decoded again'))
    assert display_preview(raw, 480, tmp_path) == preview
    assert files[0].stat().st_mtime_ns == stamp


def test_display_cache_changes_for_size_and_source_and_preserves_transparency(tmp_path):
    a = display_preview(original(), 160, tmp_path)
    b = display_preview(original(), 960, tmp_path)
    c = display_preview(original('blue'), 160, tmp_path)
    assert len({a, b, c}) == 3
    with Image.open(BytesIO(display_preview(original((0, 0, 0, 0), 'RGBA'), 160, tmp_path))) as image:
        assert image.getpixel((0, 0))[3] == 0


def test_display_respects_camera_orientation_and_rejects_oversized_decode(tmp_path, monkeypatch):
    output = BytesIO()
    exif = Image.Exif(); exif[274] = 6
    Image.new('RGB', (1200, 600), 'blue').save(output, format='JPEG', exif=exif)
    with Image.open(BytesIO(display_preview(output.getvalue(), 480, tmp_path))) as image:
        assert image.size == (240, 480)
    monkeypatch.setattr(gunpla_images, 'MAX_PREVIEW_PIXELS', 1000)
    with pytest.raises(ValueError, match='pixel limit'):
        display_preview(original(), 960, tmp_path)


def test_concurrent_display_writes_are_atomic(tmp_path):
    with ThreadPoolExecutor(max_workers=4) as pool:
        values = list(pool.map(lambda _: display_preview(original(), 480, tmp_path), range(4)))
    assert len(set(values)) == 1 and len(list(tmp_path.glob('*.webp'))) == 1
    assert not list(tmp_path.glob('*.tmp'))


def test_display_write_failure_cleans_temporary_file(tmp_path, monkeypatch):
    def unavailable(*_):
        raise OSError('fixture disk error')
    monkeypatch.setattr(gunpla_images.os, 'link', unavailable)
    with pytest.raises(OSError):
        display_preview(original(), 480, tmp_path)
    assert not list(tmp_path.iterdir())
    with pytest.raises(ValueError):
        display_preview(original(), 320, tmp_path)
    with pytest.raises(OSError):
        display_preview(b'not an image', 480, tmp_path)


def test_display_api_is_cached_conditional_and_original_is_unchanged(client, session, tmp_path):
    client.app.state.settings.artifact_dir = str(tmp_path / 'acceptance')
    client.app.state.cache = CatalogCache(client=MemoryRedis())
    asset, path = seed_image(session, tmp_path)
    url = '/api/reference-images/' + asset
    raw = path.read_bytes()
    first = client.get(url + '/display?width=480')
    second = client.get(url + '/display?width=480')
    assert first.status_code == second.status_code == 200
    assert first.headers['content-type'] == 'image/webp'
    assert second.headers['x-catalog-cache'] == 'redis'
    assert first.content == second.content
    assert client.get(url + '/display?width=480', headers={'If-None-Match': first.headers['etag']}).status_code == 304
    assert client.get(url).content == raw == path.read_bytes()
    assert client.get(url + '/display?width=4000').status_code == 422
    other, _ = seed_image(session, tmp_path, 's1.52poke.com')
    assert client.get('/api/reference-images/' + other + '/display').status_code == 404
    assert client.get('/api/reference-images/00000000-0000-0000-0000-000000000001/display').status_code == 404


def test_display_cache_cannot_bypass_login_or_logout(auth_client, session):
    directory = Path(auth_client.app.state.settings.artifact_dir).parent
    asset, _ = seed_image(session, directory)
    auth_client.app.state.cache = CatalogCache(client=MemoryRedis())
    url = '/api/reference-images/' + asset + '/display?width=160'
    assert auth_client.get(url).status_code == 401
    assert signin(auth_client).status_code == 200
    image = auth_client.get(url)
    assert image.status_code == 200 and 'no-store' in image.headers['cache-control']
    etag = {'If-None-Match': image.headers['etag']}
    assert auth_client.get(url, headers=etag).status_code == 304
    assert auth_client.post('/api/auth/logout', headers=CLIENT, json={}).status_code == 200
    assert auth_client.get(url, headers=etag).status_code == 401
