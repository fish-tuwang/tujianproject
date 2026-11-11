import hashlib
import re
from urllib.parse import urljoin, unquote
from bs4 import BeautifulSoup
from backend.app.schemas import ParsedPage, ParseIssue, SourceCandidate, TYPES
from .base import SourceParseError
from .http import normalize_url

BASE = 'https://wiki.52poke.com'
LIST_URL = BASE + '/zh-hans/宝可梦列表（按全国图鉴编号）/简单版'


def text(node):
    return node.get_text(' ', strip=True) if node else ''


def dex_number(value):
    match = re.search(r'#\s*(\d{1,4})(?!\d)', value)
    return int(match[1]) if match else None


def artwork_url(node, url, dex):
    # The infobox explicitly identifies its artwork. Some forms share another
    # dex's image, or legitimately use a Dream-named illustration in this slot.
    for image in node.find_all('img'):
        cell = image.find_parent('td')
        src = image.get('data-src') or image.get('src', '')
        if src and cell and re.search(r'官方[绘繪][图圖]', text(cell)):
            return urljoin(url, src)
    for image in node.find_all('img'):
        src = image.get('data-src') or image.get('src', '')
        if re.search(r'/' + str(dex).zfill(3) + r'[A-Za-z][^/]*\.(?:png|jpg|webp)(?:/|$)', unquote(src), re.I) and '_Dream' not in src:
            return urljoin(url, src)
    return None


class PokemonAdapter:
    def seed_urls(self):
        return [normalize_url(LIST_URL, LIST_URL, 'pokemon')]

    def discover(self, url, body):
        return self.parse(url, body).discovered_urls

    def parse(self, url, body):
        soup = BeautifulSoup(body, 'html.parser')
        page = ParsedPage(source='pokemon', url=url, content_hash=hashlib.sha256(body).hexdigest())
        if '宝可梦列表' in unquote(url):
            self.parse_national_list(url, soup, page)
        else:
            self.parse_detail(url, soup, page)
        return page

    def parse_national_list(self, url, soup, page):
        seen = set()
        for table in soup.select('.mw-parser-output table'):
            if '全国编号' not in text(table)[:500]:
                continue
            for row in table.find_all('tr'):
                cells = row.find_all(['td', 'th'], recursive=False)
                if len(cells) < 2:
                    continue
                dex = dex_number(text(cells[0]))
                if not dex or dex in seen:
                    continue
                anchors = [c.find('a', href=True) for c in cells[1:4]]
                anchor = anchors[0]
                if not anchor:
                    continue
                try:
                    target = normalize_url(url, anchor['href'], 'pokemon').split('#')[0]
                except ValueError:
                    continue
                seen.add(dex)
                page.discovered_urls.append(target)
                page.candidates.append(SourceCandidate(kind='pokemon', source_key=str(dex), fields={'dex': dex, 'name_zh': text(anchor), 'name_ja': text(anchors[1]) if len(anchors) > 1 else None, 'name_en': text(anchors[2]) if len(anchors) > 2 else None, 'source_url': target}, evidence={'url': url, 'list_entry': True}))
        if not seen:
            raise SourceParseError('national list table missing')

    def parse_detail(self, url, soup, page):
        content = soup.select_one('#mw-content-text > .mw-parser-output') or soup.select_one('#mw-content-text')
        if content is None:
            raise SourceParseError('Pokemon content missing')
        box = content.select_one('table.roundy.a-r.at-c')
        if box is None:
            box = next((t for t in content.find_all('table') if '全国图鉴' in text(t) and len(text(t)) < 16000), None)
        if box is None:
            raise SourceParseError('Pokemon infobox missing')
        dex = dex_number(text(box))
        if dex is None:
            raise SourceParseError('national number missing')
        heading = soup.select_one('#firstHeading')
        name = text(heading)
        fields = {'dex': dex, 'name_zh': name, 'source_url': url}
        header_cell = box.select_one('td.roundy')
        if header_cell:
            bold = header_cell.find_all('b')
            if len(bold) >= 3:
                fields.update(name_zh=text(bold[0]), name_ja=text(bold[1]), name_en=text(bold[2]))
        fields['types'] = []
        fields['abilities'] = []
        for row in box.find_all('tr'):
            label = text(row)
            anchors = [text(a) for a in row.find_all('a')]
            if re.search(r'属性|屬性', label) and len(label) < 220:
                fields['types'] = list(dict.fromkeys(a for a in anchors if a in TYPES)) or fields['types']
            if re.search(r'特性', label) and len(label) < 250:
                fields['abilities'] = list(dict.fromkeys(a for a in anchors if a and a not in ['特性', '隐藏特性', '隱藏特性']))
            for term, field in [('身高', 'height_m'), ('体重', 'weight_kg'), ('體重', 'weight_kg')]:
                if term in label:
                    match = re.search(r'(\d+(?:\.\d+)?)\s*(?:m|kg|米|千克)', label)
                    if match:
                        fields[field] = float(match[1])
        title = box.select_one('.name-zh')
        if title:
            fields['name_zh'] = text(title)
        for selector, field in [('.name-ja', 'name_ja'), ('.name-en', 'name_en')]:
            node = box.select_one(selector)
            if node:
                fields[field] = text(node)
        evidence = {'url': url}
        image = artwork_url(box, url, dex)
        if image:
            evidence['image_url'] = image
        page.candidates.append(SourceCandidate(kind='pokemon', source_key=str(dex), fields=fields, evidence=evidence))
        self.parse_forms(url, box, page, dex, fields)
        seen_forms = {'default'}
        for label in content.select('[class*="_toggler_show-form"]'):
            form_name = text(label)
            key = next((c.removeprefix('_toggler_show-') for c in label.get('class', []) if c.startswith('_toggler_show-form')), '')
            if not form_name or key == 'form1' or key in seen_forms:
                continue
            form_row = content.select_one('tr._toggle.' + key)
            if form_row is None:
                continue
            seen_forms.add(key)
            attributes = list(dict.fromkeys(text(a) for a in form_row.select('a[title*="（属性）"]') if text(a) in TYPES))
            stable_key = 'alola' if '阿罗拉' in form_name else hashlib.sha256(form_name.encode()).hexdigest()[:12]
            evidence = {'url': url, 'source_toggle': key}
            image = artwork_url(form_row, url, dex)
            if image:
                evidence['image_url'] = image
            page.candidates.append(SourceCandidate(kind='pokemon_form', source_key=f'{dex}:{stable_key}', fields={'dex': dex, 'form_key': stable_key, 'display_name': form_name, 'types': attributes}, evidence=evidence))
        self.parse_evolutions(url, content, page, dex)
        from .pokemon_details import parse_details
        data = parse_details(soup, url)
        if data['base_stats']:
            page.candidates.append(SourceCandidate(kind='pokemon_detail', source_key=str(dex), fields={'dex': dex, 'data': data, 'source_url': url}, evidence={'url': url}))

    def parse_forms(self, url, box, page, dex, fields):
        evidence = {'url': url}
        image = artwork_url(box, url, dex)
        if image:
            evidence['image_url'] = image
        page.candidates.append(SourceCandidate(kind='pokemon_form', source_key=f'{dex}:default', fields={'dex': dex, 'form_key': 'default', 'display_name': '通常形态', 'types': fields['types']}, evidence=evidence))
        for node in box.select('[data-form]'):
            key = node['data-form']
            page.candidates.append(SourceCandidate(kind='pokemon_form', source_key=f'{dex}:{key}', fields={'dex': dex, 'form_key': key, 'display_name': node.get('data-name', key), 'types': [text(a) for a in node.find_all('a') if text(a) in TYPES]}, evidence={'url': url}))
        for item in box.select('.tabbertab[title]'):
            label = item.get('title', '').strip()
            if label and label not in ['通常', '通常形态']:
                key = hashlib.sha256(label.encode()).hexdigest()[:12]
                page.candidates.append(SourceCandidate(kind='pokemon_form', source_key=f'{dex}:{key}', fields={'dex': dex, 'form_key': key, 'display_name': label, 'types': [text(a) for a in item.find_all('a') if text(a) in TYPES]}, evidence={'url': url}))

    def parse_evolutions(self, url, content, page, dex):
        marker = content.find(id=re.compile(r'^进化$|^進化$'))
        if marker is None:
            return
        heading = marker.find_parent(['h2', 'h3', 'h4']) or marker.parent
        nodes = []
        for sibling in heading.next_siblings:
            if getattr(sibling, 'name', '') in ['h2', 'h3', 'h4']:
                break
            nodes.append(sibling)
        for node in nodes:
            if not hasattr(node, 'find_all'):
                continue
            # 进化模板用带全国编号的Dream图片标识对象，外层表格的坐标保留箭头关系。
            if getattr(node, 'name', '') == 'table':
                self._parse_evolution_grid(node, page, url)
            for row in node.find_all('tr'):
                cells = row.find_all(['td', 'th'], recursive=False)
                numbered = [(dex_number(text(c)), c) for c in cells if dex_number(text(c))]
                if len(numbered) < 2:
                    continue
                start = numbered[0][0]
                for end, cell in numbered[1:]:
                    if start == end:
                        continue
                    condition = ' '.join(text(c) for c in cells if not dex_number(text(c)))
                    key = hashlib.sha256(f'{start}:{end}:{condition}'.encode()).hexdigest()
                    page.candidates.append(SourceCandidate(kind='evolution', source_key=key, fields={'relation_key': key, 'from_dex': start, 'to_dex': end, 'condition': condition}, evidence={'url': url}))

    def _parse_evolution_grid(self, table, page, url):
        rows = [r for r in table.find_all('tr') if r.find_parent('table') is table]
        grid = [r.find_all(['td', 'th'], recursive=False) for r in rows]
        entries = []
        for y, cells in enumerate(grid):
            for x, cell in enumerate(cells):
                image = next((i for i in cell.find_all('img') if re.search(r'/\d{3,4}[A-Za-z].*_Dream', unquote(i.get('src', '')))), None)
                stage = re.search(r'(未进化|[12]阶进化)', text(cell))
                if image is not None and stage:
                    number = int(re.search(r'/(\d{3,4})[A-Za-z]', unquote(image['src']))[1])
                    entries.append((number, 0 if stage[1] == '未进化' else int(stage[1][0]), x, y))
        for end, stage, x, y in entries:
            parents = [p for p in entries if p[1] == stage - 1]
            if not parents:
                continue
            distance = min(abs(p[2] - x) + abs(p[3] - y) for p in parents)
            closest = [p for p in parents if abs(p[2] - x) + abs(p[3] - y) == distance]
            if len(closest) != 1:
                page.issues.append(ParseIssue(code='EVOLUTION_AMBIGUOUS', message='进化分支需核对', url=url))
                continue
            start, _, px, py = closest[0]
            conditions = []
            for cy in range(min(y, py), max(y, py) + 1):
                for cx in range(min(x, px), max(x, px) + 1):
                    if cy < len(grid) and cx < len(grid[cy]):
                        cell = grid[cy][cx]
                        value = text(cell)
                        if not re.search(r'未进化|[12]阶进化', value) and re.search(r'使用|等级|亲密度|友好度|招式|交换|连接', value):
                            distance_to_midpoint = (cx - (x + px) / 2) ** 2 + (cy - (y + py) / 2) ** 2
                            conditions.append((distance_to_midpoint, value))
            condition = min(conditions, key=lambda v: v[0])[1] if conditions else ''
            key = hashlib.sha256(f'{start}:{end}:{condition}'.encode()).hexdigest()
            if not any(c.kind == 'evolution' and c.source_key == key for c in page.candidates):
                page.candidates.append(SourceCandidate(kind='evolution', source_key=key, fields={'relation_key': key, 'from_dex': start, 'to_dex': end, 'condition': condition}, evidence={'url': url}))
