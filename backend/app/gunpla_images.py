"""Small display derivatives of registered Bandai originals; original bytes stay intact."""
import hashlib
import os
from io import BytesIO
from pathlib import Path
import tempfile
from urllib.parse import urlsplit
from uuid import UUID

import anyio
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from PIL import Image, ImageOps
from sqlalchemy.orm import Session

from .api import get_session
from .reference_images import cached_reference, read_reference
from .repository import CatalogError, CatalogRepository

router = APIRouter(prefix='/api/reference-images')
PREVIEW_WIDTHS = (160, 480, 960)
MAX_PREVIEW_PIXELS = 12_000_000


def display_preview(original, width, directory):
    if width not in PREVIEW_WIDTHS:
        raise ValueError('unsupported display size')
    digest = hashlib.sha256(b'gunpla-webp-v1:' + str(width).encode() + b':' + original).hexdigest()
    directory = Path(directory)
    target = directory / (digest + '.webp')
    if target.exists():
        return target.read_bytes()
    with Image.open(BytesIO(original)) as image:
        if image.width * image.height > MAX_PREVIEW_PIXELS:
            raise ValueError('display image exceeds pixel limit')
        image.draft('RGB', (width, width))
        image = ImageOps.exif_transpose(image)
        image.thumbnail((width, width), Image.Resampling.LANCZOS)
        image = image.convert('RGBA' if image.mode in {'RGBA', 'LA', 'P'} else 'RGB')
        output = BytesIO()
        image.save(output, format='WEBP', quality=85, method=4)
    data = output.getvalue()
    directory.mkdir(parents=True, exist_ok=True)
    file = tempfile.NamedTemporaryFile(dir=directory, suffix='.tmp', delete=False)
    temporary = Path(file.name)
    try:
        with file:
            file.write(data)
        try:
            os.link(temporary, target)
        except FileExistsError:
            pass  # Content-addressed files are immutable; the first writer wins.
    finally:
        temporary.unlink(missing_ok=True)
    return data


@router.get('/{asset_id}/display')
async def preview_image(asset_id: UUID, request: Request, session: Session = Depends(get_session), width: int = Query(480)):
    if width not in PREVIEW_WIDTHS:
        raise CatalogError('INVALID_PARAMETERS', '展示图片尺寸不支持', 422)
    cache = request.app.state.cache
    key = f'gunpla-preview:v1:{asset_id}:{width}'
    data = cache.get(key)
    origin = 'redis'
    if data is None:
        def load():
            try:
                value = CatalogRepository(session).image(str(asset_id))
            finally:
                session.close()
            url = value.get('source_image_url')
            if not url or urlsplit(url).hostname != 'staticcdn.bandaihobbysite.cn':
                raise CatalogError('NOT_FOUND', '高达展示图片未收录', 404)
            directory = Path(request.app.state.settings.artifact_dir).parent
            original = cache.get('image:' + str(asset_id))
            if original is None:
                original = read_reference(asset_id, url, directory / 'reference-images')
            if original is None:
                path, _ = cached_reference(asset_id, url, directory / 'reference-images')
                original = path.read_bytes()
            try:
                return display_preview(original, width, directory / 'gunpla-previews')
            except (OSError, ValueError, Image.DecompressionBombError) as error:
                raise CatalogError('IMAGE_PREVIEW_UNAVAILABLE', '展示图片暂不可用', 502) from error
        data = await anyio.to_thread.run_sync(load, limiter=request.app.state.preview_limiter)
        cache.set(key, data, ttl=86400)
        origin = 'display-cache'
    etag = '"' + hashlib.sha256(data).hexdigest() + '"'
    headers = {'ETag': etag, 'Cache-Control': 'public, max-age=86400', 'X-Content-Type-Options': 'nosniff', 'X-Catalog-Cache': origin}
    if request.headers.get('if-none-match') == etag:
        return Response(status_code=304, headers=headers)
    return Response(data, media_type='image/webp', headers=headers)
