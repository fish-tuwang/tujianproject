"""Serve verified official images from writable and legacy catalogue caches."""
from pathlib import Path
import re

from fastapi import Request
from fastapi.responses import FileResponse

from .config import ROOT
from .reference_images import image_type
from .repository import CatalogError

IMAGE_URL = re.compile(r'/api/tomica/official-images/([a-f0-9]{64})')


def media_directories(settings):
    directory = Path(settings.artifact_dir)
    directory = directory if directory.is_absolute() else ROOT / directory
    return directory / 'tomica-mall-backfill/published', directory.parent / 'tomica-official-media'


def image_urls(value):
    if isinstance(value, dict):
        return {key: image_urls(item) for key, item in value.items()}
    if isinstance(value, list):
        return [image_urls(item) for item in value]
    if isinstance(value, str):
        match = IMAGE_URL.fullmatch(value)
        if match:
            return '/api/tomica-mall-images/' + match[1]
    return value


def serve_image(digest: str, request: Request):
    if not re.fullmatch(r'[a-f0-9]{64}', digest):
        raise CatalogError('NOT_FOUND', '\u56fe\u7247\u672a\u6536\u5f55', 404)
    for directory in media_directories(request.app.state.settings):
        path = directory / (digest + '.image')
        if path.is_file():
            with path.open('rb') as stream:
                mime = image_type(stream.read(32))
            return FileResponse(path, media_type=mime,
                headers={'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})
    raise CatalogError('NOT_FOUND', '\u56fe\u7247\u672a\u6536\u5f55', 404)
