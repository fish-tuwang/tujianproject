from io import BytesIO
from types import SimpleNamespace
import hashlib

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
import pytest

from backend.app.auth import install_auth
from backend.app.config import Settings
from backend.app.repository import CatalogError
from backend.app.tomica_mall_media import image_urls, media_directories, serve_image


def test_image_projection_preserves_product_sources_and_original_payload():
    old='/api/tomica/official-images/'+'a'*64
    product={'preview_image_url':old,'official_products':[{'images':[{'url':old,'kind':'packaging'}],
        'source_url':'https://takaratomymall.jp/shop/g/g4904810092421/'}]}
    result=image_urls(product)
    assert result['preview_image_url']=='/api/tomica-mall-images/'+'a'*64
    assert result['official_products'][0]['images'][0]['url']==result['preview_image_url']
    assert result['official_products'][0]['source_url']==product['official_products'][0]['source_url']
    assert product['preview_image_url']==old
    assert image_urls(old+'bad')==old+'bad'


@pytest.mark.parametrize('legacy',[False,True])
def test_image_service_reads_new_writable_cache_and_existing_legacy_cache(tmp_path,legacy):
    settings=SimpleNamespace(artifact_dir=str(tmp_path/'acceptance'))
    output=BytesIO();Image.new('RGB',(12,12),'red').save(output,'PNG');body=output.getvalue()
    digest=hashlib.sha256(body).hexdigest()
    target=media_directories(settings)[1 if legacy else 0]
    target.mkdir(parents=True);(target/(digest+'.image')).write_bytes(body)
    app=FastAPI();app.state.settings=settings
    app.add_api_route('/image/{digest}',serve_image)
    with TestClient(app) as client:
        response=client.get('/image/'+digest)
    assert response.status_code==200 and response.content==body
    assert response.headers['content-type']=='image/png'
    assert response.headers['cache-control']=='private, no-store'


@pytest.mark.parametrize('digest',['../private','a'*64])
def test_missing_or_invalid_digest_does_not_read_other_paths(tmp_path,digest):
    request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=SimpleNamespace(artifact_dir=str(tmp_path)))))
    with pytest.raises(CatalogError):serve_image(digest,request)


def test_new_image_path_requires_existing_catalog_login(tmp_path):
    app=FastAPI();app.add_api_route('/api/tomica-mall-images/{digest}',serve_image)
    install_auth(app,Settings(_env_file=None,auth_enabled=True,auth_store_path=str(tmp_path/'accounts.sqlite3'),artifact_dir=str(tmp_path/'logs')))
    with TestClient(app) as client:response=client.get('/api/tomica-mall-images/'+'a'*64)
    assert response.status_code==401
