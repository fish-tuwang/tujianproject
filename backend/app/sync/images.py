from dataclasses import dataclass
from datetime import timedelta
import hashlib
import ipaddress
import socket
from urllib.parse import urlsplit
import httpx
import boto3
from backend.app.models import ImageAsset, now

ALLOWED_HOSTS = {'tomica.minibird.jp', 's1.52poke.com'}
MAX_BYTES = 10 * 1024 * 1024


def validate_image_url(url, resolver=socket.getaddrinfo):
    parsed = urlsplit(url)
    if parsed.scheme not in {'http', 'https'} or parsed.hostname not in ALLOWED_HOSTS or parsed.username or parsed.password or parsed.port:
        raise ValueError('image URL outside allowed source')
    for record in resolver(parsed.hostname, 443 if parsed.scheme == 'https' else 80, type=socket.SOCK_STREAM):
        if not ipaddress.ip_address(record[4][0]).is_global:
            raise ValueError('private image address rejected')


@dataclass
class ImageResult:
    asset_id: str
    status: str
    public_url: str | None = None
    error: str | None = None


class ImageService:
    def __init__(self, session, settings, *, downloader=None, s3=None, clock=now):
        self.session, self.settings, self.downloader, self.s3, self.clock = session, settings, downloader, s3, clock

    def download(self, url):
        with httpx.Client(timeout=20, follow_redirects=False) as client:
            for redirects in range(4):
                validate_image_url(url)
                with client.stream('GET', url) as response:
                    if response.is_redirect:
                        if redirects == 3:
                            raise ValueError('image redirect limit')
                        from urllib.parse import urljoin
                        url = urljoin(url, response.headers.get('location', ''))
                        continue
                    response.raise_for_status()
                    result = bytearray()
                    for chunk in response.iter_bytes():
                        result.extend(chunk)
                        if len(result) > MAX_BYTES:
                            raise ValueError('image too large')
                    if not response.headers.get('content-type', '').startswith('image/'):
                        raise ValueError('not an image')
                    return bytes(result)
        raise ValueError('image download failed')

    def process_asset(self, asset_id):
        asset = self.session.get(ImageAsset, str(asset_id))
        if asset is None:
            return ImageResult(str(asset_id), 'missing')
        if asset.rights_status != 'approved' or not asset.rights_reference:
            return ImageResult(asset.id, 'pending')
        if asset.status == 'ready':
            return ImageResult(asset.id, 'ready', asset.public_url)
        try:
            if not self.settings.public_image_base_url.startswith('https://'):
                raise ValueError('HTTPS image delivery not configured')
            data = (self.downloader or self.download)(asset.source_url)
            if len(data) > MAX_BYTES:
                raise ValueError('image too large')
            signatures = [(b'\x89PNG\r\n\x1a\n', 'png', 'image/png'), (b'\xff\xd8\xff', 'jpg', 'image/jpeg'), (b'GIF8', 'gif', 'image/gif')]
            match = next((s for s in signatures if data.startswith(s[0])), None)
            if data.startswith(b'RIFF') and data[8:12] == b'WEBP':
                match = (b'RIFF', 'webp', 'image/webp')
            if not match:
                raise ValueError('invalid image signature')
            digest = hashlib.sha256(data).hexdigest()
            key = f'catalog/{digest}.{match[1]}'
            s3 = self.s3 or boto3.client('s3', endpoint_url=self.settings.object_store_endpoint, aws_access_key_id=self.settings.object_store_access_key.get_secret_value(), aws_secret_access_key=self.settings.object_store_secret_key.get_secret_value())
            s3.put_object(Bucket=self.settings.object_store_bucket, Key=key, Body=data, ContentType=match[2])
            asset.content_hash, asset.object_key, asset.public_url = digest, key, self.settings.public_image_base_url.rstrip('/') + '/' + key
            asset.status, asset.last_error = 'ready', None
            from sqlalchemy import select
            from backend.app.models import Pokemon, PokemonForm, TomicaModel, TomicaVariant
            from backend.app.repository import CatalogRepository
            for source, models in [('tomica', [(TomicaModel, 'primary_image_id'), (TomicaVariant, 'image_id')]), ('pokemon', [(Pokemon, 'primary_image_id'), (PokemonForm, 'image_id')])]:
                if any(self.session.scalar(select(model.id).where(getattr(model, column) == asset.id).limit(1)) for model, column in models):
                    CatalogRepository(self.session).bump_revision(source)
        except Exception as error:
            asset.status, asset.last_error = 'failed', str(error)[:300]
            asset.attempts += 1
            asset.next_retry_at = self.clock() + timedelta(seconds=min(3600, 60 * 2 ** min(asset.attempts, 5)))
        self.session.flush()
        return ImageResult(asset.id, asset.status, asset.public_url, asset.last_error)
