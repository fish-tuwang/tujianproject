from typing import Annotated
from uuid import UUID
from pathlib import Path
from functools import partial
import hashlib
import anyio
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session
from .repository import CatalogError, CatalogRepository
from .schemas import PokemonQuery, TomicaQuery

router = APIRouter(prefix='/api')


def get_session(request: Request):
    with request.app.state.session_factory() as session:
        try:
            yield session
        except Exception:
            session.rollback()
            raise


def public_cached(request, session, source, view, params, loader, missing='条目未收录', ttl=600):
    cache = request.app.state.cache
    repo = CatalogRepository(session, cache)
    revision = repo.get_revision(source)
    key = f'api:{source}:{revision}:{view}:' + cache.signature(params)
    value = cache.get_json(key)
    if value is not None:
        return JSONResponse(value, headers={'X-Catalog-Cache': 'hit'})
    value = cache.remember(key, lambda: loader(repo), ttl=ttl)
    if value is None:
        raise CatalogError('NOT_FOUND', missing, 404)
    return JSONResponse(jsonable_encoder(value), headers={'X-Catalog-Cache': 'miss'})


@router.get('/reference-images/{asset_id}')
async def reference_image(asset_id: UUID, request: Request, session: Session = Depends(get_session)):
    from .reference_images import cached_reference, image_type, read_reference
    cache = request.app.state.cache
    key = 'image:' + str(asset_id)
    data = cache.get(key)
    origin = 'redis'
    if data is not None:
        mime = image_type(data)
    else:
        def metadata():
            try:
                return CatalogRepository(session).image(str(asset_id))
            finally:
                session.close()  # A slow image download must not hold a DB connection.
        value = await anyio.to_thread.run_sync(metadata)
        if not value.get('source_image_url'):
            raise CatalogError('NOT_FOUND', '图片未收录', 404)
        directory = Path(request.app.state.settings.artifact_dir).parent / 'reference-images'
        args = (asset_id, value['source_image_url'], directory)
        data = await anyio.to_thread.run_sync(partial(read_reference, *args))
        origin = 'disk'
        if data is None:
            path, mime = await anyio.to_thread.run_sync(partial(cached_reference, *args), limiter=request.app.state.image_limiter)
            data = await anyio.to_thread.run_sync(path.read_bytes)
            origin = 'source'
        mime = image_type(data)
        cache.set(key, data, ttl=86400)
    etag = '"' + hashlib.sha256(data).hexdigest() + '"'
    headers = {'Cache-Control': 'public, max-age=86400', 'X-Content-Type-Options': 'nosniff', 'ETag': etag, 'X-Catalog-Cache': origin}
    if request.headers.get('if-none-match') == etag:
        return Response(status_code=304, headers=headers)
    return Response(data, media_type=mime, headers=headers)


@router.get('/tomica')
def list_tomica(request: Request, query: Annotated[TomicaQuery, Query()], session: Session = Depends(get_session)):
    return public_cached(request, session, 'tomica', 'list-v4', query.model_dump(), lambda repo: repo.list_tomica(query))


@router.get('/tomica/filters')
def tomica_filters(request: Request, session: Session = Depends(get_session)):
    return public_cached(request, session, 'tomica', 'filters', {}, lambda repo: repo.get_tomica_filters())


@router.get('/tomica/{model_id}')
def tomica_detail(request: Request, model_id: UUID, session: Session = Depends(get_session)):
    return public_cached(request, session, 'tomica', 'detail', str(model_id), lambda repo: repo.get_tomica(model_id), '车型未收录', ttl=86400)


@router.get('/pokemon')
def list_pokemon(request: Request, query: Annotated[PokemonQuery, Query()], session: Session = Depends(get_session)):
    from .pokemon_regions import region_index_version
    return public_cached(request, session, 'pokemon', 'list-regions-' + region_index_version(), query.model_dump(), lambda repo: repo.list_pokemon(query))


@router.get('/pokemon/regions')
def pokemon_regions(request: Request, session: Session = Depends(get_session)):
    from .pokemon_regions import region_index_version, region_metadata
    return public_cached(request, session, 'pokemon', 'regions-' + region_index_version(), {}, lambda repo: region_metadata(), ttl=86400)


@router.get('/pokemon/{dex}')
def pokemon_detail(request: Request, dex: int, session: Session = Depends(get_session)):
    return public_cached(request, session, 'pokemon', 'detail', dex, lambda repo: repo.get_pokemon(dex), '宝可梦未收录', ttl=86400)
