"""Source artwork cache for preview; never marks publication rights approved."""
import hashlib
from pathlib import Path
import threading
import time
from urllib.parse import urlsplit

import httpx
from .repository import CatalogError
from .sync.images import MAX_BYTES, validate_image_url

LOCKS = {host: threading.Lock() for host in ('tomica.minibird.jp', 's1.52poke.com')}
LAST_REQUEST = {}
REFERENCE_CACHE_SECONDS = 30 * 86400


def image_type(data):
    for signature, mime in [(b'\x89PNG\r\n\x1a\n', 'image/png'), (b'\xff\xd8\xff', 'image/jpeg'), (b'GIF8', 'image/gif')]:
        if data.startswith(signature):
            return mime
    if data.startswith(b'RIFF') and data[8:12] == b'WEBP':
        return 'image/webp'
    raise ValueError('invalid image signature')


def reference_path(asset_id, url, directory):
    key = hashlib.sha256((str(asset_id) + ':' + url).encode()).hexdigest()
    return Path(directory) / (key + '.image')


def read_reference(asset_id, url, directory):
    if urlsplit(url).hostname not in LOCKS:
        raise ValueError('source not allowed')
    target = reference_path(asset_id, url, directory)
    if target.exists() and time.time() - target.stat().st_mtime < REFERENCE_CACHE_SECONDS:
        data = target.read_bytes()
        image_type(data)
        return data
    return None


def cached_reference(asset_id, url, directory, *, transport=None, validate=validate_image_url):
    host = urlsplit(url).hostname
    if host not in LOCKS:
        raise ValueError('source not allowed')
    directory = Path(directory)
    target = reference_path(asset_id, url, directory)
    data = read_reference(asset_id, url, directory)
    if data is not None:
        return target, image_type(data)
    with LOCKS[host]:
        if target.exists() and time.time() - target.stat().st_mtime < REFERENCE_CACHE_SECONDS:
            return target, image_type(target.read_bytes()[:32])
        try:
            validate(url)
            time.sleep(max(0, 2 - (time.monotonic() - LAST_REQUEST.get(host, 0))))
            LAST_REQUEST[host] = time.monotonic()
            referer = 'https://wiki.52poke.com/' if host == 's1.52poke.com' else 'http://tomica.minibird.jp/t-tomica/'
            # Request the image as a resource of its recorded public source page.
            with httpx.Client(timeout=20, follow_redirects=False, transport=transport) as client:
                with client.stream('GET', url, headers={'Referer': referer, 'User-Agent': 'DualCatalog/0.1'}) as response:
                    response.raise_for_status()
                    if not response.headers.get('content-type', '').startswith('image/'):
                        raise ValueError('not an image')
                    data = bytearray()
                    for chunk in response.iter_bytes():
                        data.extend(chunk)
                        if len(data) > MAX_BYTES:
                            raise ValueError('image too large')
            mime = image_type(data)
            directory.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix('.tmp')
            temporary.write_bytes(data)
            temporary.replace(target)
            return target, mime
        except (httpx.HTTPError, ValueError):
            if target.exists():
                return target, image_type(target.read_bytes()[:32])
            raise CatalogError('SOURCE_IMAGE_UNAVAILABLE', '源站原图暂不可用', 502)
