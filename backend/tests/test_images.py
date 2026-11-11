import pytest
from backend.app.models import ImageAsset
from backend.app.config import Settings
from backend.app.sync.images import ImageService, validate_image_url


def test_pending_does_not_download(session):
    image = ImageAsset(source_url='http://tomica.minibird.jp/t-tomica/test.jpg')
    session.add(image); session.flush()
    def forbidden(url): raise AssertionError('pending image downloaded')
    result = ImageService(session, Settings(_env_file=None), downloader=forbidden).process_asset(image.id)
    assert result.status == 'pending'


@pytest.mark.parametrize('url', ['http://127.0.0.1/a.png', 'https://evil.test/a.png', 'https://user:pw@s1.52poke.com/a.png'])
def test_image_host_boundary(url):
    with pytest.raises(ValueError): validate_image_url(url)


def test_private_dns_rejected():
    with pytest.raises(ValueError):
        validate_image_url('https://s1.52poke.com/a.png', resolver=lambda *a,**k: [(0,0,0,'',('127.0.0.1',443))])


def test_bandai_cdn_requires_https_and_a_public_address():
    public = lambda *a, **k: [(0, 0, 0, '', ('203.1.1.1', 443))]
    validate_image_url('https://staticcdn.bandaihobbysite.cn/www/uploads/model.jpg', resolver=public)
    for url in ['http://staticcdn.bandaihobbysite.cn/www/uploads/model.jpg', 'https://staticcdn.bandaihobbysite.cn.evil.test/a.jpg', 'https://staticcdn.bandaihobbysite.cn:443/a.jpg']:
        with pytest.raises(ValueError):
            validate_image_url(url, resolver=public)
    with pytest.raises(ValueError):
        validate_image_url('https://staticcdn.bandaihobbysite.cn/a.jpg', resolver=lambda *a, **k: [(0, 0, 0, '', ('127.0.0.1', 443))])


def test_upload_failure_retry_and_idempotency(session):
    image = ImageAsset(source_url='https://s1.52poke.com/a.png', rights_status='approved', rights_reference='internal-test-evidence')
    session.add(image); session.flush()
    settings = Settings(_env_file=None, public_image_base_url='https://images.example.test')
    class Storage:
        calls=0
        def put_object(self, **kwargs): self.calls += 1
    storage = Storage()
    service = ImageService(session, settings, downloader=lambda u:b'bad', s3=storage)
    assert service.process_asset(image.id).status == 'failed' and image.attempts == 1
    service.downloader=lambda u:b'\x89PNG\r\n\x1a\nvalid-test-payload'
    assert service.process_asset(image.id).status == 'ready'
    assert service.process_asset(image.id).status == 'ready' and storage.calls == 1
