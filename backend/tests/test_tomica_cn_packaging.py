from io import BytesIO
import hashlib
import json

import httpx
from PIL import Image
import pytest

from backend.app import tomica_mall_backfill as module


def reviewed_record():
    stream = BytesIO()
    Image.new('RGB', (100, 80), 'red').save(stream, 'PNG')
    body = stream.getvalue()
    raw = {'jan': '4904810000001', 'name': 'exact reviewed car',
           'source_url': 'https://takaratomymall.jp/shop/g/g4904810000001/'}
    url = 'https://www.tomy.cn/wp-content/uploads/2026/11/box.png'
    record = {'sku': '000001', 'jp_name': raw['name'], 'jan_source_url': raw['source_url'],
              'source_url': 'https://www.tomy.cn/tomica/item/01diecastcar/example',
              'review': 'visual_review_20261125', 'gallery_urls': [url],
              'packaging_image': {'url': url, 'sha256': hashlib.sha256(body).hexdigest()}}
    return raw, record, body


def test_verified_chinese_box_is_downloaded_with_exact_content_checksum(tmp_path, monkeypatch):
    raw, record, body = reviewed_record()
    monkeypatch.setattr(module, 'CN_PACKAGING', {raw['jan']: record})
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(
            200, content=body, headers={'Content-Type': 'image/png'}))) as client:
        image = module.supplemental_box(raw, tmp_path, client)
    assert image['kind'] == 'packaging'
    assert image['sha256'] == record['packaging_image']['sha256']
    assert (tmp_path / image['path']).read_bytes() == body


@pytest.mark.parametrize('changed', ['sku', 'jp_name', 'jan_source_url', 'source_url', 'review', 'gallery', 'checksum'])
def test_wrong_identity_source_or_image_is_never_used_as_a_box(tmp_path, monkeypatch, changed):
    raw, record, body = reviewed_record()
    if changed in {'sku', 'jp_name', 'jan_source_url', 'source_url', 'review'}:
        record[changed] = 'wrong'
    elif changed == 'gallery':
        record['gallery_urls'] = []
    else:
        record['packaging_image']['sha256'] = 'a' * 64
    monkeypatch.setattr(module, 'CN_PACKAGING', {raw['jan']: record})
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(
            200, content=body, headers={'Content-Type': 'image/png'}))) as client:
        with pytest.raises(ValueError):
            module.supplemental_box(raw, tmp_path, client)


@pytest.mark.parametrize('url', [
    'http://www.tomy.cn/wp-content/uploads/2026/11/box.jpg',
    'https://www.tomy.cn/wp-json/box.jpg',
    'https://www.tomy.cn.evil.example/wp-content/uploads/2026/11/box.jpg',
    'https://www.tomy.cn/wp-content/uploads/2026/11/box.jpg?token=x',
])
def test_chinese_source_scope_is_limited_to_public_uploaded_images(url):
    with pytest.raises(ValueError):
        module.image_url(url)


def test_committed_boxes_have_unique_exact_product_identity_and_seeded_photos():
    inventory = json.loads(module.INVENTORY.read_text(encoding='utf-8'))['products']
    for jan, record in module.CN_PACKAGING.items():
        peers = [p for p in inventory if p['jan'].endswith(record['sku'].lstrip('Xx').removesuffix('CN'))]
        assert len(peers) == 1 and peers[0]['jan'] == jan
        assert record['jp_name'] == peers[0]['name']
        assert record['jan_source_url'] == peers[0]['source_url']
        assert record['packaging_image']['url'] in record['gallery_urls']
        assert record['review'] == 'visual_review_20261125'
        assert module.SEED_IMAGES[record['packaging_image']['url']] == record['packaging_image']['sha256']
