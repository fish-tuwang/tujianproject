from io import BytesIO
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import httpx
from PIL import Image, ImageDraw
import pytest

from backend.app.models import SourceIdentity, TomicaModel
from backend.app.tomica_mall_backfill import (GalleryBackfill, image_url, list_packaging_covers,
    prepare_image, same_picture)


def picture(size=640, different=False):
    image=Image.new('RGB',(size,size),'white')
    draw=ImageDraw.Draw(image)
    draw.rectangle((size//6,size//3,size*5//6,size*2//3),fill='blue' if different else 'red')
    draw.ellipse((size//4,size*3//5,size//3,size*3//4),fill='black')
    output=BytesIO();image.save(output,'PNG');return output.getvalue()


def test_original_requires_bigger_matching_content():
    assert same_picture(picture(240),picture())
    assert not same_picture(picture(240),picture(different=True))
    assert not same_picture(picture(240),picture(240))


@pytest.mark.parametrize('url',['http://takaratomymall.jp/img/goods/a.jpg','https://other.example/img/goods/a.jpg','https://takaratomymall.jp/shop/g/g1/','https://takaratomymall.jp/img/goods/a.jpg?token=x','https://user@takaratomymall.jp/img/goods/a.jpg'])
def test_image_source_boundary(url):
    with pytest.raises(ValueError):image_url(url)


def test_download_resolves_original_and_preserves_verified_package(tmp_path):
    calls=[]
    def source(request):
        calls.append(request.url.path)
        return httpx.Response(200,content=picture(240 if '/6/' in request.url.path else 640),headers={'Content-Type':'image/png'})
    with httpx.Client(transport=httpx.MockTransport(source)) as client:
        result=prepare_image('https://takaratomymall.jp/img/goods/6/car.png',True,set(),tmp_path,client)
        assert result['url']=='https://takaratomymall.jp/img/goods/5/car.png'
        assert result['kind']=='packaging' and result['status']=='downloaded'
        assert (tmp_path/result['path']).is_file()
        prepare_image('https://takaratomymall.jp/img/goods/6/car.png',True,set(),tmp_path,client)
    assert len(calls)==2


def test_wrong_original_does_not_become_a_published_image(tmp_path):
    def source(request):return httpx.Response(200,content=picture(240) if '/6/' in request.url.path else picture(different=True),headers={'Content-Type':'image/png'})
    with httpx.Client(transport=httpx.MockTransport(source)) as client,pytest.raises(ValueError,match='does not match'):
        prepare_image('https://takaratomymall.jp/img/goods/6/car.png',False,set(),tmp_path,client)


def test_recorded_gallery_original_is_reused_without_guessing_another_url(tmp_path):
    calls=[]
    def source(request):
        calls.append(request.url.path)
        if '/5/' in request.url.path:raise AssertionError('recorded original was not reused')
        return httpx.Response(200,content=picture(240 if '/6/' in request.url.path else 640),headers={'Content-Type':'image/png'})
    with httpx.Client(transport=httpx.MockTransport(source)) as client:
        full=prepare_image('https://takaratomymall.jp/img/goods/L/car.png',False,set(),tmp_path,client)
        result=prepare_image('https://takaratomymall.jp/img/goods/6/car.png',True,set(),tmp_path,client,[full])
    assert result['url']==full['url'] and result['kind']=='packaging'
    assert len(calls)==2


def test_list_cover_uses_verified_box_and_preserves_other_items_and_detail(session,monkeypatch):
    monkeypatch.setitem(sys.modules,'backend.app.tomica_official',SimpleNamespace(SOURCE='test-official'))
    models=[TomicaModel(name_original='one',number='1'),TomicaModel(name_original='two',number='2')]
    session.add_all(models);session.flush()
    session.add_all([SourceIdentity(source='test-official',kind='product',source_key=str(i),entity_id=m.id,evidence={'packaging_status':status,'images':[{'kind':'gallery','sha256':'a'*64},{'kind':'packaging','sha256':'b'*64}]}) for i,(m,status) in enumerate(zip(models,['verified','unverified']))]);session.flush()
    value={'items':[{'id':m.id,'image_url':'car.jpg','preview_image_url':'car-preview.jpg'} for m in models]}
    result=list_packaging_covers(value,session)
    assert result['items'][0]['image_url'] is None
    assert result['items'][0]['preview_image_url'].endswith('b'*64)
    assert result['items'][1]['image_url']=='car.jpg'
    detail={'id':models[0].id,'image_url':'car.jpg','official_products':[{'images':['car','box']}]}
    assert list_packaging_covers(detail,session)==detail


def make_job(tmp_path):
    app=SimpleNamespace(state=SimpleNamespace(settings=SimpleNamespace(artifact_dir=str(tmp_path))))
    collector=SimpleNamespace(canonical_name=lambda name:name.replace(' ',''),parse_snapshot=lambda raw:dict(raw,eligibility='review',release_date=None))
    return GalleryBackfill(app,collector)


def test_existing_date_and_label_are_kept_for_unchanged_verified_barcode(tmp_path):
    job=make_job(tmp_path)
    raw={'jan':'4904810950509','source_url':'https://takaratomymall.jp/shop/g/g4904810950509/','name':'Tomica No.132'}
    existing=SimpleNamespace(evidence=dict(raw,release_date='2026-06-20',eligibility_reason='verified diecast'))
    doc=job.document(raw,existing)
    assert doc['release_date']=='2026-06-20' and doc['eligibility']=='accepted'
    with pytest.raises(ValueError,match='barcode/source'):
        job.document(dict(raw,jan='4904810950508'),existing)


def test_damaged_official_label_repair_requires_same_barcode_and_number(tmp_path):
    job=make_job(tmp_path)
    raw={'jan':'4904810950509','source_url':'https://takaratomymall.jp/shop/g/g4904810950509/','name':'Tomica No.132 truck'}
    existing=SimpleNamespace(evidence=dict(raw,name='Tomica No.132 \ufffd'))
    assert job.document(raw,existing)['name']==raw['name']
    assert existing.evidence['name']==raw['name']
    existing.evidence=dict(raw,name='Tomica No.131 \ufffd')
    with pytest.raises(ValueError,match='name changed'):
        job.document(raw,existing)
    existing.evidence=dict(raw,name='Tomica No.132 different clean name')
    with pytest.raises(ValueError,match='name changed'):
        job.document(raw,existing)


def test_product_gallery_resolves_changed_original_filename(tmp_path):
    def source(request):
        path=request.url.path
        if path.startswith('/shop/'):
            return httpx.Response(200,text='<main><a rel="shadowbox[group]" href="/img/goods/5/actual.png"><img></a></main>')
        if path.endswith('/car.png') and '/5/' in path:return httpx.Response(404)
        return httpx.Response(200,content=picture(240 if '/6/' in path else 640),headers={'Content-Type':'image/png'})
    with httpx.Client(transport=httpx.MockTransport(source)) as client:
        image=prepare_image('https://takaratomymall.jp/img/goods/6/car.png',False,set(),tmp_path,client,product_url='https://takaratomymall.jp/shop/g/g4904810746829/')
    assert image['url'].endswith('/5/actual.png')


def test_seeded_official_image_requires_committed_content_checksum(tmp_path,monkeypatch):
    import hashlib
    from backend.app import tomica_mall_backfill as module
    url='https://takaratomymall.jp/img/goods/L/recorded.png'
    digest=hashlib.sha256(picture()).hexdigest()
    monkeypatch.setattr(module,'SEED_IMAGES',{url:digest})
    def source(request):
        assert request.url.host=='117.72.11.77'
        return httpx.Response(200,content=picture(),headers={'Content-Type':'application/octet-stream'})
    with httpx.Client(transport=httpx.MockTransport(source)) as client:
        result=prepare_image(url,True,set(),tmp_path,client)
        assert result['sha256']==digest and result['url']==url
    monkeypatch.setattr(module,'SEED_IMAGES',{url:'a'*64})
    fresh=tmp_path/'other';fresh.mkdir()
    with httpx.Client(transport=httpx.MockTransport(source)) as client,pytest.raises(ValueError,match='checksum mismatch'):
        prepare_image(url,False,set(),fresh,client)


def test_only_explicit_official_release_day_is_used(tmp_path):
    job=make_job(tmp_path)
    row={'jan':'4904810092162','source_url':'https://takaratomymall.jp/shop/g/g4904810092162/','name':'Tomica No.58','text':'\u767a\u58f2\u65e5\uff1a2026\u5e7412\u670819\u65e5'}
    assert job.document(row,None)['release_date']=='2026-12-19'
    row['text']='2026 collection'
    assert job.document(row,None)['release_date'] is None


def test_recorded_catalogue_review_must_match_name_and_source(tmp_path):
    job=make_job(tmp_path)
    row={'jan':'4904810092162','source_url':'https://takaratomymall.jp/shop/g/g4904810092162/','name':'TLV vehicle'}
    row['catalog_review']={'source_url':row['source_url'],'reviewed_name':row['name'],'decision':'accepted','reason':'official named TLV vehicle listing'}
    assert job.document(row,None)['eligibility']=='accepted'
    row['name']='different merchandise'
    with pytest.raises(ValueError,match='review does not match'):job.document(row,None)


@pytest.mark.parametrize('reviewed',[False,True])
@pytest.mark.parametrize('has_original',[True,False])
def test_unavailable_primary_never_invents_an_original_or_hides_a_model(session,tmp_path,has_original,reviewed):
    from concurrent.futures import ThreadPoolExecutor
    import hashlib
    calls=[];published=[]
    thumb='https://takaratomymall.jp/img/goods/6/4904810072041.jpg'
    original='https://takaratomymall.jp/img/goods/L/4904810072041.jpg'
    raw={'jan':'4904810072041','source_url':'https://takaratomymall.jp/shop/g/g4904810072041/','name':'official vehicle','images':[thumb]+([original] if has_original else []),'deferred_originals':[thumb]}
    if reviewed:
        raw['model_review']={'model_id':'base-model','model_name':'official vehicle','source_name':raw['name'],
            'variant_id':'base-variant','variant_code':None,'source_url':raw['source_url'],'reason':'source image and sole variant reviewed'}
    def publish(session,document,directory,cache,review=None):
        assert review==({key:raw['model_review'][key] for key in ('model_id','model_name','source_name','variant_id','variant_code')} if reviewed else None)
        published.append(document)
        assert all((directory/i['path']).is_file() for i in document['images'])
        return {'action':'created','model_id':'test'}
    collector=SimpleNamespace(SOURCE='test-official',parse_snapshot=lambda raw:dict(raw,eligibility='accepted',release_date=None),publish=publish)
    app=SimpleNamespace(state=SimpleNamespace(settings=SimpleNamespace(artifact_dir=str(tmp_path)),session_factory=lambda:session))
    job=GalleryBackfill(app,collector)
    def source(request):
        calls.append(str(request.url))
        return httpx.Response(200,content=picture(640 if '/L/' in request.url.path else 240),headers={'Content-Type':'image/png'})
    with httpx.Client(transport=httpx.MockTransport(source)) as client,ThreadPoolExecutor(max_workers=1) as pool:
        result=job.publish_one(raw,tmp_path,tmp_path,client,pool)
    assert result['action']=='created' and result['deferred_originals']==[thumb]
    assert result['thumbnail_only'] is (not has_original)
    assert calls==[original if has_original else thumb]
    assert published[0]['images'][0]['kind']==('gallery' if has_original else 'thumbnail')
    assert published[0]['images'][0]['sha256']==hashlib.sha256(picture(640 if has_original else 240)).hexdigest()


def test_reviewed_label_transition_keeps_exact_existing_identity(tmp_path):
    job=make_job(tmp_path)
    raw={'jan':'4904810091905','source_url':'https://takaratomymall.jp/shop/g/g4904810091905/','name':'Long Tomica No.136 drill'}
    previous=dict(raw,name='Tomica No.136 drill')
    existing=SimpleNamespace(entity_id='same-model',evidence=previous)
    raw['reviewed_identity']={'model_id':'same-model','previous_name':previous['name'],'name':raw['name'],'source_url':raw['source_url'],'reason':'reviewed format only'}
    assert job.document(raw,existing)['name']==raw['name']
    existing.evidence=previous;raw['reviewed_identity']['model_id']='another-model'
    with pytest.raises(ValueError,match='name changed'):job.document(raw,existing)


@pytest.mark.parametrize('same_name',[False,True])
def test_new_sourced_sku_is_not_guessed_into_partial_historical_peers(session,tmp_path,same_name):
    model=TomicaModel(series='Tomica',number='58',name_original='new product' if same_name else 'different historical car')
    session.add(model);session.flush()
    job=make_job(tmp_path)
    doc={'jan':'4904810092162','source_url':'https://takaratomymall.jp/shop/g/g4904810092162/','name':'new product'}
    decision=job.review_new_product(session,doc,{'action':'review','reason':'ambiguous model/edition','candidates':[model.id]})
    if same_name:assert decision is None
    else:
        assert decision['action']=='create' and decision['reviewed_candidates']==[model.id]
        assert len(decision['catalog_sha256'])==64
        assert (job.directory/'identity-reviews'/(doc['jan']+'.json')).exists()
    assert model.name_original==('new product' if same_name else 'different historical car')
