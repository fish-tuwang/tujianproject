import httpx
import pytest
from backend.app.reference_images import cached_reference, image_type, LAST_REQUEST
from backend.app.repository import CatalogError


def test_reference_keeps_original_bytes_and_caches(tmp_path):
    data = b'RIFF' + b'1234' + b'WEBP' + b'original pixels'
    calls = []
    def handler(request):
        calls.append(request)
        assert request.headers['referer'] == 'https://wiki.52poke.com/'
        return httpx.Response(200, content=data, headers={'content-type': 'image/webp'})
    LAST_REQUEST.clear()
    args = ('registered-id', 'https://s1.52poke.com/wiki/a.png', tmp_path)
    path, mime = cached_reference(*args, transport=httpx.MockTransport(handler), validate=lambda _: None)
    assert mime == 'image/webp' and path.read_bytes() == data
    assert cached_reference(*args, transport=httpx.MockTransport(handler), validate=lambda _: None)[0] == path
    assert len(calls) == 1


def test_html_error_is_not_published_as_picture(tmp_path):
    LAST_REQUEST.clear()
    with pytest.raises(CatalogError, match='原图暂不可用'):
        cached_reference('id', 'https://s1.52poke.com/wiki/a.png', tmp_path, validate=lambda _: None,
                         transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b'<html>blocked</html>', headers={'content-type': 'image/png'})))
    assert not list(tmp_path.iterdir())


def test_unknown_reference_host_and_svg_are_rejected(tmp_path):
    with pytest.raises(ValueError):
        cached_reference('id', 'http://127.0.0.1/a.png', tmp_path)
    with pytest.raises(ValueError):
        image_type(b'<svg onload="alert(1)"></svg>')


def test_bandai_original_is_not_modified_and_uses_its_own_referer(tmp_path):
    data = b'\xff\xd8\xfforiginal Bandai fixture bytes'
    calls = []
    def respond(request):
        calls.append(request)
        assert request.headers['referer'] == 'https://bandaihobbysite.cn/gunpla'
        return httpx.Response(200, content=data, headers={'content-type': 'image/jpeg'})
    LAST_REQUEST.clear()
    args = ('bandai-registered', 'https://staticcdn.bandaihobbysite.cn/www/uploads/model.jpg', tmp_path)
    original, mime = cached_reference(*args, transport=httpx.MockTransport(respond), validate=lambda _: None)
    assert original.read_bytes() == data and mime == 'image/jpeg'
    assert cached_reference(*args, transport=httpx.MockTransport(respond), validate=lambda _: None)[0] == original
    assert len(calls) == 1
