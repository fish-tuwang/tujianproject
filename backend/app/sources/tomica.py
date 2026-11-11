import hashlib
import json
import re
import unicodedata
from urllib.parse import urljoin, unquote
from bs4 import BeautifulSoup
from backend.app.schemas import ParsedPage, ParseIssue, SourceCandidate
from .base import SourceParseError
from .http import normalize_url

BASE = 'http://tomica.minibird.jp/t-tomica/'
MODEL_TITLE = re.compile(r'^((?:[FLS]?\d{1,3}-\d+[A-Z]?)|(?:L-\d+[A-Z]?)|(?:S\d+)|(?:SP(?:-\d+[A-Z]?)?))(?=\s|　|$)', re.I)


def normalized_title(node):
    return unicodedata.normalize('NFKC', node.get_text(' ', strip=True))
BRANDS = {'トヨタ': 'Toyota', 'コロナ': 'Toyota', 'クラウン': 'Toyota', 'セリカ': 'Toyota', '日産': 'Nissan', 'ブルーバード': 'Nissan', 'スカイライン': 'Nissan', 'フェアレディ': 'Nissan', 'ホンダ': 'Honda', 'Honda': 'Honda', '三菱ふそう': 'Mitsubishi Fuso', 'ふそう': 'Mitsubishi Fuso', '三菱': 'Mitsubishi', '日野': 'Hino', 'いすゞ': 'Isuzu', 'マツダ': 'Mazda', 'スバル': 'Subaru', 'スズキ': 'Suzuki', 'ダイハツ': 'Daihatsu', 'ポルシェ': 'Porsche', 'フェラーリ': 'Ferrari', 'ランボルギーニ': 'Lamborghini', 'メルセデス': 'Mercedes-Benz', 'BMW': 'BMW', 'フォルクスワーゲン': 'Volkswagen'}


BRANDS.update({'ニッサン': 'Nissan', 'NISSAN': 'Nissan', 'TOYOTA': 'Toyota', 'MAZDA': 'Mazda', 'SUBARU': 'Subaru', 'SUZUKI': 'Suzuki'})


def normalize_brand(name):
    return next((brand for term, brand in BRANDS.items() if term.casefold() in name.casefold()), None)


class TomicaAdapter:
    def seed_urls(self):
        return [BASE + 'menu.html']

    def discover(self, url, body):
        return self.parse(url, body).discovered_urls

    def parse_menu(self, url, soup):
        return sorted(self._links(url, soup, only_sections=True), key=lambda value: (0 if '/number/' in value else 1, value))

    def _links(self, url, soup, only_sections=False):
        result = set()
        for anchor in soup.select('a[href]'):
            try:
                href = normalize_url(url, anchor['href'], 'tomica').split('#')[0]
                path = unquote(href)
                if path.endswith(('.html', '.htm')) and (not only_sections or any('/' + s + '/' in path for s in ['number', 'special', 'gift', 'event', 'character', 'notsold'])):
                    result.add(href)
            except ValueError:
                continue
        return sorted(result)

    def parse(self, url, body):
        # Some updated pages contain UTF-8 bytes despite their old Shift_JIS
        # declaration. Strict UTF-8 first also handles ASCII without guessing.
        try:
            text = body.decode('utf-8-sig')
        except UnicodeDecodeError:
            charset = re.search(rb'charset\s*=\s*[\'"]?([a-z0-9_-]+)', body[:4096], re.I)
            # These legacy EUC pages also use extended JIS Roman numerals.
            legacy = 'euc_jis_2004' if charset and charset[1].lower() in {b'euc-jp', b'euc_jp', b'x-euc-jp'} else 'cp932'
            text = body.decode(legacy, errors='replace')
        soup = BeautifulSoup(text, 'html.parser')
        page = ParsedPage(source='tomica', url=url, content_hash=hashlib.sha256(body).hexdigest())
        if url.split('#')[0].endswith('menu.html'):
            page.discovered_urls = self.parse_menu(url, soup)
            if not page.discovered_urls:
                raise SourceParseError('Tomica menu structure missing')
            return page
        if '/number/' in url:
            self.parse_number_page(url, soup, page)
        else:
            self.parse_supplement_page(url, soup, page)
        page.discovered_urls = self._links(url, soup)
        return page

    def parse_number_page(self, url, soup, page):
        def is_model_heading(node):
            cell = node.find_parent(['td', 'th'])
            table = node.find_parent('table')
            if cell is None or table is None or int(cell.get('colspan', 1)) < 2:
                return False
            first_row = next((r for r in table.find_all('tr') if r.find_parent('table') is table), None)
            return cell.find_parent('tr') is first_row
        anchors = [a for a in soup.select('a[name],a[id]') if MODEL_TITLE.match(normalized_title(a)) and is_model_heading(a)]
        anchors += [b for b in soup.find_all('b') if MODEL_TITLE.match(normalized_title(b)) and not b.select_one('a[name],a[id]') and not b.find_parent('a') and is_model_heading(b)]
        if not anchors:
            raise SourceParseError('Tomica model anchors missing')
        for anchor in anchors:
            raw_anchor = anchor.get('name', anchor.get('id')) or MODEL_TITLE.match(normalized_title(anchor))[1]
            # 源站存在锚点006-5误用于006-13、039-8重复用于A/B的情况，优先采用标题中明确的车型标识。
            title_code = MODEL_TITLE.match(normalized_title(anchor))
            key = title_code[1].upper() if title_code else raw_anchor
            table = anchor.find_parent('table')
            if table is None:
                page.issues.append(ParseIssue(code='TABLE_MISSING', message='车型缺少表格', url=url, locator=key))
                continue
            header = anchor.find_parent('td').get_text(' ', strip=True)
            name = re.sub(r'^' + re.escape(key) + r'\s*', '', normalized_title(anchor)).strip()
            if not name:
                page.issues.append(ParseIssue(code='EMPTY_SOURCE_HEADING', message='源站空白模板标题，不创建无名称条目', url=url, locator=raw_anchor))
                continue
            date = re.search(r'((?:19|20)\d{2})\.(\d{1,2})\s*[～~]', header)
            scale = re.search(r'1/\d+', header)
            legacy = bool(re.fullmatch(r'S\d+', key))
            special = key.startswith(('SP', 'L-')) or legacy
            fields = {'number': key if special else key.split('-')[0], 'generation': '' if special else key.split('-')[1], 'name_original': name, 'brand': normalize_brand(name), 'release_year': int(date[1]) if date else None, 'release_month': int(date[2]) if date else None, 'scale': scale[0] if scale else None, 'source_url': url, 'source_locator': key, 'series': 'Tomica Special Legacy' if legacy else 'Tomica Special' if key.startswith('SP') else 'Tomica Long' if key.startswith('L-') else 'Tomica Foreign' if key.startswith('F') else 'Tomica'}
            images = sorted({urljoin(url, image['src']) for image in table.find_all('img', src=True) if not any(term in image['src'].casefold() for term in ['wanted', 'logo', 'banner'])})
            evidence = {'url': url, 'anchor': raw_anchor, 'title_code': key, 'display_title': ' '.join(name.split()), 'image_urls': images, 'raw_header': header}
            if key == 'SP':
                if not images:
                    page.issues.append(ParseIssue(code='IDENTITY_AMBIGUOUS', message='无编号且无图片身份依据，保留待核对', url=url, locator=raw_anchor))
                    continue
                fingerprint = {'url': url, 'title': evidence['display_title'], 'images': images}
                key = 'SP:' + hashlib.sha256(json.dumps(fingerprint, sort_keys=True).encode()).hexdigest()[:32]
            model_candidate = SourceCandidate(kind='tomica_model', source_key=key, fields=fields, evidence=evidence)
            existing_model = next((c for c in page.candidates if c.kind == 'tomica_model' and c.source_key == key), None)
            if existing_model and existing_model.fields == fields:
                continue
            page.candidates.append(model_candidate)
            if key != raw_anchor:
                page.issues.append(ParseIssue(code='ANCHOR_TITLE_DIFFERENCE', message='采用标题明确标识，保留原锚点证据', url=url, locator=raw_anchor, severity='info'))
            rows = [r for r in table.find_all('tr') if r.find_parent('table') is table]
            seen = set()
            for i, row in enumerate(rows):
                cells = row.find_all(['td', 'th'], recursive=False)
                for col, cell in enumerate(cells):
                    image = cell.find('img')
                    if image is None or 'WANTED' in cell.get_text().upper():
                        continue
                    image_url = urljoin(url, image.get('src', ''))
                    if not image.get('src') or any(t in image_url.casefold() for t in ['wanted', 'logo', 'banner']):
                        continue
                    previous = rows[i - 1].find_all(['td', 'th'], recursive=False) if i else []
                    following = rows[i + 1].find_all(['td', 'th'], recursive=False) if i + 1 < len(rows) else []
                    label = previous[col].get_text(' ', strip=True) if col < len(previous) else ''
                    code = re.search(r'(?<!\d)\d{1,3}-\d+-\d+(?!\d)', label)
                    description = following[col].get_text(' ', strip=True) if col < len(following) else ''
                    variant_key = key + ':' + (code[0] if code else hashlib.sha256(image_url.encode()).hexdigest()[:24])
                    if variant_key in seen:
                        page.issues.append(ParseIssue(code='DUPLICATE_VERSION', message='版本编码重复，需核对', url=url, locator=variant_key))
                        continue
                    seen.add(variant_key)
                    country = next((c for c in ['JAPAN', 'CHINA', 'VIETNAM'] if c in description.upper()), None)
                    page.candidates.append(SourceCandidate(kind='tomica_variant', source_key=variant_key, fields={'variant_code': code[0] if code else None, 'description': description, 'country': country, 'source_url': url}, evidence={'url': url, 'model_key': key, 'image_url': image_url, 'original_label': label}))

    def parse_supplement_page(self, url, soup, page):
        for anchor in soup.select('a[href]'):
            href = urljoin(url, anchor['href'])
            match = re.search(r'/number/[^#]+#([FLS]?\d{1,3}-\d+)', href, re.I)
            if match:
                page.issues.append(ParseIssue(code='SUPPLEMENT_REFERENCE', message=anchor.get_text(' ', strip=True), url=url, locator=match[1], severity='info'))
        heading = soup.find('font', attrs={'size': '+2'}) or soup.title
        context = normalized_title(heading) if heading else ''
        context = re.sub(r'^(?:coleection|collection)\s*', '', context, flags=re.I).strip()
        section = next((s for s in ['special', 'gift', 'event', 'character', 'notsold'] if '/' + s + '/' in url), None)
        if section is None:
            return
        series = 'Tomica Dream' if 'ドリームトミカ' in context else {'special': 'Tomica Custom', 'gift': 'Tomica Gift', 'event': 'Tomica Event', 'character': 'Tomica Character', 'notsold': 'Tomica Not For Sale'}[section]
        seen = set()
        # Only leaf tables contain product cells. Parent layout tables would pair
        # a caption with photographs from unrelated nested products.
        for table in soup.find_all('table'):
            if table.find('table'):
                continue
            rows = [r for r in table.find_all('tr') if r.find_parent('table') is table]
            group = ''
            for index, row in enumerate(rows):
                cells = self._cell_columns(row)
                if len(cells) == 1 and cells[0][2] > 1 and not row.find('img'):
                    group = normalized_title(cells[0][0])
                for cell, start, end in cells:
                    photos = []
                    for image in cell.select('img[src]'):
                        src = image['src']
                        if not re.search(r'\.(?:jpe?g|png|webp)$', src, re.I) or any(t in src.casefold() for t in ['wanted', 'logo', 'banner', 'title', 'check']):
                            continue
                        if 'WANTED' in cell.get_text().upper():
                            continue
                        photo = urljoin(url, src)
                        try:
                            normalize_url(url, photo, 'tomica')
                        except (ValueError, UnicodeError):
                            continue
                        if photo not in photos:
                            photos.append(photo)
                    if not photos:
                        continue
                    caption = (self._column_text(rows[index - 1], start, end) if index else '') or normalized_title(cell)
                    description = self._column_text(rows[index + 1], start, end) if index + 1 < len(rows) else ''
                    # In consecutive photo/reference rows, the preceding base
                    # model link describes the preceding photo. Keep the model
                    # reference below this photo as its own description.
                    if caption != group and index >= 2 and any(left < end and right > start and other.find('img') for other, left, right in self._cell_columns(rows[index - 2])) and any(left < end and right > start and any('/number/' in a['href'] for a in other.select('a[href]')) for other, left, right in self._cell_columns(rows[index - 1])):
                        caption = ''
                    indexed_product = re.match(r'^(?:No\.?\s*)?(?:[A-Z]{1,5}-?)?\d{1,3}(?:-\d+[A-Z]?)?(?=\s|$)', caption, re.I)
                    if len(cells) > 1 and caption == group and not description and not indexed_product:
                        caption = ''  # A shared heading cannot name separate cars.
                    if not caption and not description:
                        page.issues.append(ParseIssue(code='SUPPLEMENT_CAPTION_MISSING', message='原图相邻同列无可信名称，保留待核对', url=url, locator=photos[0]))
                        continue
                    fingerprint = normalize_url(url, photos[0], 'tomica')
                    key = 'edition:' + hashlib.sha256(fingerprint.encode()).hexdigest()[:32]
                    if key in seen:
                        continue
                    seen.add(key)
                    parts = list(dict.fromkeys(p for p in [caption, group, context, description] if p))
                    name = ' · '.join(parts)
                    codes = [re.match(r'^(?:No\.\s*)?((?:[A-Z]{1,5}-?)?\d+(?:-\d+[A-Z]?)?|SP)(?=\s|$)', text, re.I) for text in [caption, description]]
                    code = next((match for match in codes if match), None)
                    fields = {'series': series, 'number': code[1] if code else 'SP' if re.match(r'^SP(?:\s|$)', description) else '—', 'generation': '', 'name_original': name, 'brand': normalize_brand(description) or normalize_brand(caption), 'release_year': None, 'release_month': None, 'scale': None, 'source_url': url, 'source_locator': key}
                    evidence = {'url': url, 'image_urls': photos, 'caption': caption, 'group': group, 'description': description}
                    page.candidates.append(SourceCandidate(kind='tomica_model', source_key=key, fields=fields, evidence=evidence))
                    for photo in photos:
                        suffix = hashlib.sha256(normalize_url(url, photo, 'tomica').encode()).hexdigest()[:24]
                        country = next((c for c in ['JAPAN', 'CHINA', 'VIETNAM'] if c in description.upper()), None)
                        page.candidates.append(SourceCandidate(kind='tomica_variant', source_key=key + ':' + suffix, fields={'variant_code': caption or None, 'description': ' · '.join(p for p in [group, caption, description] if p), 'special_orderer': context if section in {'special', 'gift'} else None, 'country': country, 'source_url': url}, evidence={'url': url, 'model_key': key, 'image_url': photo}))

    @staticmethod
    def _cell_columns(row):
        result, column = [], 0
        for cell in row.find_all(['td', 'th'], recursive=False):
            width = max(1, int(cell.get('colspan', 1)))
            result.append((cell, column, column + width))
            column += width
        return result

    @classmethod
    def _column_text(cls, row, start, end):
        values = [normalized_title(cell) for cell, left, right in cls._cell_columns(row) if left < end and right > start and not cell.find('img')]
        return ' / '.join(dict.fromkeys(value for value in values if value))
