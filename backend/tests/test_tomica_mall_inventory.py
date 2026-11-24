import json,re
from pathlib import Path
from urllib.parse import urlsplit

INVENTORY=Path(__file__).parents[1]/'data/tomica-mall-inventory.json'


def test_official_inventory_has_all_observed_categories_and_pages():
    data=json.loads(INVENTORY.read_text(encoding='utf-8'))
    assert len(data['category_counts'])==22
    assert len(data['listing_pages'])==32
    assert all(c['found']==c['expected'] for c in data['category_counts'])
    assert len(data['products'])==1111
    assert sum(len(p['images']) for p in data['products'])==5392
    assert len({p['jan'] for p in data['products']})==len(data['products'])


def test_official_inventory_images_are_recorded_public_source_urls():
    data=json.loads(INVENTORY.read_text(encoding='utf-8'))
    for product in data['products']:
        assert re.fullmatch(r'\d{13}',product['jan'])
        assert product['source_url']=='https://takaratomymall.jp/shop/g/g'+product['jan']+'/'
        assert product['name'].strip() and product['category_ids'] and product['images']
        assert len(product['images'])==len(set(product['images']))
        for url in product['images']:
            parts=urlsplit(url)
            assert parts.scheme=='https' and parts.netloc=='takaratomymall.jp'
            assert parts.path.startswith('/img/goods/') and not parts.query and not parts.fragment
        assert set(product.get('verified_packaging_images',[]))<=set(product['images'])


def test_132_packaging_is_visually_verified_source_image_not_assumed_last_image():
    data=json.loads(INVENTORY.read_text(encoding='utf-8'))
    product=next(p for p in data['products'] if p['jan']=='4904810950509')
    assert len(product['images'])==6
    assert product['verified_packaging_images']==['https://takaratomymall.jp/img/goods/3/4904810950509_rer2kr1w3.jpg']
    assert sum('verified_packaging_images' in p for p in data['products'])==data['packaging_review']['verified_packaging_products']==468
