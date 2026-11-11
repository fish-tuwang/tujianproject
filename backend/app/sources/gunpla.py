"""Official Gunpla facts: exact card covers and complete product-only galleries."""
from collections import OrderedDict
from datetime import date
import hashlib
import re
import unicodedata
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup
from .base import SourceParseError
from .http import normalize_url

BASE = 'https://bandaihobbysite.cn'
EXCLUDED_BRANDS = {'69', '88', '86', '123'}
SALE_TYPES = {'1': '常规商品', '2': '线上售卖', '3': '高达基地限定', '4': '活动限定'}
# The Chinese index omits this item's sale tag; Bandai's own release explicitly
# announces nationwide retail distribution. Apply only to this exact identity.
VERIFIED_SALE_TYPES = {'993': {'name': 'HGCC 1/144 ∀高达', 'types': ['1'], 'evidence': 'https://prtimes.jp/main/html/rd/p/000000768.000002607.html'}}
# Specific accessory products whose official titles include compatible model names.
VERIFIED_ACCESSORIES = {'2993', '2863', '3245', '233', '2990', '2920', '976'}


def clean(value):
    return re.sub(r'\s+', ' ', re.sub('[\u200b-\u200f\ufeff]', '', str(value))).strip()


def soup(body):
    try:
        return BeautifulSoup(body.decode('utf-8-sig') if isinstance(body, bytes) else body, 'html.parser')
    except UnicodeError as error:
        raise SourceParseError('invalid official UTF-8 page') from error


def image_url(value):
    if not value:
        return None
    value = urljoin(BASE, value)
    parts = urlsplit(value)
    if parts.scheme != 'https' or parts.hostname != 'staticcdn.bandaihobbysite.cn' or parts.username or parts.password or parts.port or parts.query or parts.fragment or not parts.path.startswith(('/www/uploads/', '/www/assets/')) or '..' in parts.path.split('/') or '\\' in parts.path:
        raise SourceParseError('image outside official CDN boundary')
    return value


def image(node):
    return image_url(node.get('data-src') or node.get('data-original') or node.get('src')) if node else None


def unique(values):
    return list(dict.fromkeys(v for v in values if v))


def text(node):
    return clean(node.get_text(' ', strip=True)) if node else ''


def parse_date(value):
    match = re.search(r'(\d{4})年\s*(\d{1,2})月(?:\s*(\d{1,2})日)?', value or '')
    if not match:
        return None, None
    year, month, day = match.groups()
    try:
        sort = date(int(year), int(month), int(day or 1)).isoformat()
    except ValueError:
        return None, None
    return sort, 'day' if day else 'month'


def parse_home(body):
    root = soup(body).select_one('main')
    if root is None:
        raise SourceParseError('Gunpla home main section missing')
    entries, indices = [], {'brand': OrderedDict(), 'series': OrderedDict()}
    for anchor in root.select('a[href]'):
        match = re.fullmatch(r'/index/index/(brand|series)/cate/([1-9][0-9]*)', anchor['href'])
        if not match:
            continue
        kind, key = match.groups()
        if kind == 'brand' and key in EXCLUDED_BRANDS:
            continue
        item = {'kind': kind, 'source_key': key, 'name': text(anchor), 'data': {'official_id': key, 'logo_url': image(anchor.select_one('img')), 'source_url': BASE + anchor['href']}}
        indices[kind].pop(key, None)
        indices[kind][key] = item
    if len(indices['brand']) < 8 or not indices['series']:
        raise SourceParseError('official model indices are incomplete')
    for values in indices.values():
        entries.extend(values.values())
    notices = OrderedDict()
    for anchor in root.select('a.p-card__event[href]'):
        title = text(anchor.select_one('.p-card__eventTit'))
        url = urljoin(BASE, anchor['href'])
        if not title:
            continue
        key = hashlib.sha256(url.encode()).hexdigest()
        notices[key] = {'kind': 'event', 'source_key': key, 'name': title, 'data': {'source_url': url, 'cover_url': image(anchor.select_one('.p-card__eventImage img')), 'channel': text(anchor.select_one('.p-card__eventTag02')), 'status_text': text(anchor.select_one('.p-card__eventTags')), 'date_text': text(anchor.select_one('.p-card__eventDate'))}}
    entries.extend(notices.values())
    notices = OrderedDict()
    for title in root.select('.p-newslist__tit'):
        anchor = title.find_parent('a', href=True)
        if not anchor or not any(text(tag) == '新商品' for tag in anchor.select('.p-newslist__tag')):
            continue
        url = urljoin(BASE, anchor['href'])
        key = hashlib.sha256(url.encode()).hexdigest()
        notices[key] = {'kind': 'announcement', 'source_key': key, 'name': text(title), 'data': {'source_url': url, 'date_text': text(anchor.select_one('.p-newslist__date'))}}
    entries.extend(notices.values())
    return entries


def prices(root):
    result = {'price_cny_text': None, 'price_jpy_text': None}
    for value in root.select('.p-card__price'):
        label, amount = text(value.select_one('.p-card__priceLabel')), text(value.select_one('.p-card__priceValue'))
        if amount:
            result['price_jpy_text' if '日本' in label else 'price_cny_text'] = amount
    return result


def parse_listing(url, body):
    url = normalize_url(url, url, 'gunpla')
    parts = urlsplit(url)
    grade = re.search(r'/brand/cate/(\d+)', parts.path)
    context = parse_qs(parts.query).get('tag', [None])[0]
    root = soup(body).select_one('main')
    if root is None:
        raise SourceParseError('listing main section missing')
    items = []
    for anchor in root.select('a.p-card[href]'):
        match = re.fullmatch(r'/index/index/detail/id/([1-9][0-9]*)', anchor['href'])
        title = text(anchor.select_one('.p-card__tit'))
        if not match or not title:
            continue
        badges = unique(key for badge in anchor.select('.p-card__tag') for key, label in SALE_TYPES.items() if text(badge) == label)
        if context:
            badges = unique([*badges, context])
        release = re.sub(r'发售$', '', text(anchor.select_one('.p-card_date'))).strip() or None
        sort, precision = parse_date(release)
        items.append({'official_id': match[1], 'name': title, 'brand_ids': [grade[1]] if grade else [], 'sale_types': badges, 'cover_url': image(anchor.select_one('.p-card__img img')), 'source_url': BASE + anchor['href'], 'release_text': release, 'release_sort': sort, 'release_precision': precision, **prices(anchor)})
    pages = {1}
    for anchor in root.select('a[href]'):
        target = urlsplit(urljoin(url, anchor['href']))
        query = parse_qs(target.query)
        if target.path == parts.path and query.get('tag', [None])[0] == context:
            value = query.get('page', ['1'])[0]
            if value.isdigit() and 1 <= int(value) <= 2000:
                pages.add(int(value))
    return {'items': items, 'pages': max(pages)}


def parse_product(url, body, listing):
    url = normalize_url(url, url, 'gunpla')
    key = re.search(r'/detail/id/(\d+)$', url).group(1)
    root = soup(body).select_one('main')
    if root is None or not root.select_one('h1'):
        raise SourceParseError('product heading missing')
    gallery = unique(image_url(a['href']) for a in root.select('.js-swiper__main a.swiper-slide[data-fancybox="gallery"][href]'))
    details = unique(image(i) for i in root.select('.pg-products__instruction img'))
    data = {key: value for key, value in listing.items() if key not in {'name'}}
    data.update({'official_id': key, 'source_url': url, 'gallery_urls': gallery, 'detail_image_urls': [u for u in details if u not in gallery]})
    for label in root.select('.pg-products__detail dt'):
        value = label.find_next_sibling('dd')
        label, amount = text(label), text(value)
        if '日本' in label and '价' in label:
            data['price_jpy_text'] = amount or None
        elif '价' in label:
            data['price_cny_text'] = amount or None
        elif '发售日期' in label:
            data['release_text'] = amount or None
    data['release_sort'], data['release_precision'] = parse_date(data.get('release_text'))
    brands, series = [], []
    for anchor in root.select('.pg-products__linkWrap a[href]'):
        match = re.fullmatch(r'/index/index/(brand|series)/cate/(\d+)', anchor['href'])
        if match:
            (brands if match[1] == 'brand' else series).append(match[2])
    data['brand_ids'] = unique([*data.get('brand_ids', []), *brands])
    data['series_ids'] = unique(series)
    name = text(root.select_one('h1'))
    verified = VERIFIED_SALE_TYPES.get(key)
    if not data.get('sale_types') and verified and verified['name'] == name:
        data['sale_types'] = verified['types'].copy()
        data['classification_evidence'] = verified['evidence']
    match = re.search(r'(?<!\d)1\s*/\s*(\d{1,4})(?!\d)', unicodedata.normalize('NFKC', name))
    data['scale'] = '1/' + match[1] if match else None
    if not gallery:
        if not data.get('cover_url'):
            raise SourceParseError('product has no registered artwork')
        data['gallery_urls'] = [data['cover_url']]
    return {'kind': 'product', 'source_key': key, 'name': name, 'data': data}


def is_model_product(product, allowed_series_ids):
    data, name = product['data'], product['name']
    if set(data.get('brand_ids', [])) & EXCLUDED_BRANDS:
        return False, 'accessory_brand'
    if str(data.get('official_id', product.get('source_key', ''))) in VERIFIED_ACCESSORIES:
        return False, 'standalone_accessory'
    series = set(data.get('series_ids', []))
    if series and not series.intersection(allowed_series_ids):
        return False, 'non_gundam_work'
    # Inspect product names, never the included-parts description of a real model.
    subject = re.sub(r'[（(](?:含|附带|附属).*?[）)]', '', name)
    subject = re.split(r'[+＋]', subject, maxsplit=1)[0]
    subject = unicodedata.normalize('NFKC', subject)
    if re.match(r'^HGBD:R\b.*(?:武器|组件|weapons|unit)$', subject, re.I) or '外形提升零件' in subject:
        return False, 'standalone_accessory'
    accessories = r'^(?:HGBC|HG BUILD CUSTOM)(?:\s|$)|水贴|可动底座|展示底座|独立支架|LED(?:发光|灯光)?(?:组件|套组|灯组)|(?:发光|灯光)组件|灯组|(?:武器|武装|配件|扩张|扩充|扩展|选配)(?:零件|组件|配件|套组|套装|套件|部件|组合|包)|骨架(?:\s*[\[【（(]|$)'
    if re.search(accessories, subject, re.I):
        return False, 'standalone_accessory'
    return True, None
