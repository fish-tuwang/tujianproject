"""Structured facts from the source's detail tables, preserving game/form context."""
import re
import unicodedata
from urllib.parse import unquote, urljoin
from bs4 import Tag


def text(node):
    value = node.get_text(' ', strip=True) if node else ''
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', value)).strip()


def rows(table):
    return [r for r in table.find_all('tr') if r.find_parent('table') is table]


def cells(row):
    return row.find_all(['td', 'th'], recursive=False)


def sections(soup, pattern):
    for marker in soup.find_all('span', class_='mw-headline', id=re.compile(pattern)):
        heading = marker.find_parent(re.compile(r'^h[2-6]$'))
        if not heading:
            continue
        nodes = []
        for node in heading.next_siblings:
            if not isinstance(node, Tag):
                continue
            if re.fullmatch(r'h[2-6]', node.name) and node.name <= heading.name:
                break
            nodes.append(node)
        yield heading, nodes


def tables(nodes):
    for node in nodes:
        if node.name == 'table':
            yield node
        yield from node.find_all('table')


def form_context(table):
    tab = table.find_parent(class_='tabbertab')
    if tab and tab.get('title'):
        return tab['title']
    toggle = table.find_parent(class_='toggle-content')
    if toggle:
        for cls in toggle.get('class', []):
            if re.fullmatch(r'toggle-\d+\w*', cls):
                selector = toggle.find_previous(class_='toggle-p-' + cls.removeprefix('toggle-'))
                if selector and text(selector):
                    return text(selector)
                return '通常形态' if cls == 'toggle-1' else '形态 ' + cls.split('-')[-1]
    return ''


def base_stats(soup):
    result = []
    names = ['HP', '攻击', '防御', '特攻', '特防', '速度']
    for _, nodes in sections(soup, r'^种族值$'):
        for table in tables(nodes):
            values = []
            for row in rows(table):
                key = next((name for name in names if 'bgl-' + name in row.get('class', [])), None)
                if key:
                    match = re.search(r'[:：]\s*(\d+)', text(cells(row)[0]))
                    if match:
                        values.append({'name': key, 'value': int(match[1])})
            if len(values) == 6:
                label = form_context(table)
                heading = table.find_previous(['h3', 'h4', 'h5'])
                if not label and heading and '种族值' not in text(heading):
                    label = text(heading)
                result.append({'label': label or '通常形态', 'stats': values, 'total': sum(v['value'] for v in values)})
    return result


def acquisition(soup):
    result = []
    for _, nodes in sections(soup, r'^获得方式$'):
        for table in tables(nodes):
            direct = rows(table)
            if not any([text(c) for c in cells(r)] == ['宝可梦', '游戏版本', '地点', '方式', '备注'] for r in direct):
                continue
            spans = {}
            for row in direct:
                generation = next((c[1:] for c in row.get('class', []) if re.fullmatch(r'g\d+', c)), None)
                if generation is None:
                    continue
                grid = {x: value for x, (remaining, value) in spans.items() if remaining > 0}
                spans = {x: (remaining - 1, value) for x, (remaining, value) in spans.items() if remaining > 1}
                col = 0
                for cell in cells(row):
                    if 'hide' in cell.get('class', []):
                        continue
                    while col in grid:
                        col += 1
                    value = text(cell)
                    if col == 0 and not value:
                        icon = cell.select_one('[title]')
                        value = '形态 ' + icon['title'] if icon else '通常形态'
                    width = int(cell.get('colspan', 1))
                    height = max(1, int(cell.get('rowspan', 1)))
                    for offset in range(width):
                        entry = value if offset == 0 else ''
                        grid[col + offset] = entry
                        if height > 1:
                            spans[col + offset] = (height - 1, entry)
                    col += width
                if grid.get(1):
                    result.append({'generation': int(generation), 'form': grid.get(0, ''), 'games': grid.get(1, ''), 'location': grid.get(2, ''), 'method': grid.get(3, ''), 'note': grid.get(4, '')})
    return result


def matchups(soup):
    result = []
    for _, nodes in sections(soup, r'^[属屬]性相性$'):
        for table in tables(nodes):
            direct = rows(table)
            if not direct or '进攻招式属性' not in text(direct[0]):
                continue
            types = [text(c) for c in cells(direct[0])[1:]]
            if len(types) != 18:
                continue
            context = form_context(table) or '一般'
            for row in direct[1:]:
                values = cells(row)
                if len(values) < 18:
                    continue
                multipliers = [text(c).replace(' ', '').replace('⁄', '/') for c in values[-18:]]
                if not any(re.fullmatch(r'\d+(?:/\d+)?', v) for v in multipliers):
                    continue
                label = ' / '.join(filter(None, [text(c) for c in values[:-18] if text(c) != '未知']))
                result.append({'label': context + (' · ' + label if label else ''), 'types': [{'name': name, 'multiplier': value} for name, value in zip(types, multipliers) if value]})
    return result


def movesets(soup):
    result = []
    pattern = r'^(可学会的招式|能使用的招式学习器|蛋招式|特殊招式|传授招式|回忆招式)(?:_\d+)?$'
    for heading, nodes in sections(soup, pattern):
        method = text(heading)
        game_heading = heading.find_previous('h4')
        game = text(game_heading) if game_heading and '《' in text(game_heading) else '源站所列版本'
        for table in tables(nodes):
            if 'sortable' not in table.get('class', []):
                continue
            values = []
            for row in rows(table):
                entries = cells(row)
                attribute = next((i for i, c in enumerate(entries) if c.find('a', title=re.compile(r'[（(]属性[）)]$'))), None)
                if attribute is None or attribute == 0 or len(entries) < attribute + 4:
                    continue
                name_cell = entries[attribute - 1]
                move = re.sub(r'\s*\[详\].*$', '', text(name_cell)).strip()
                if not move:
                    continue
                prefix = ' / '.join(text(c) for c in entries[:attribute - 1] if text(c) and 'hide' not in c.get('class', []))
                link = name_cell.find('a', href=True)
                timed = len(entries) == attribute + 4
                values.append({'learn': prefix, 'name': move, 'type': text(entries[attribute]), 'category': text(entries[attribute + 1]), 'power': text(entries[attribute + 2]), 'accuracy': None if timed else text(entries[attribute + 3]), 'pp': None if timed else text(entries[attribute + 4]), 'cooldown': text(entries[attribute + 3]) if timed else None, 'source_url': urljoin('https://wiki.52poke.com', link['href']) if link else None})
            if values:
                result.append({'game': game, 'form': form_context(table) or '通常形态', 'method': method, 'kind': 'machine' if '学习器' in method else 'learn', 'moves': values})
    return result


def shiny_pairs(soup, url):
    result = []
    for _, nodes in sections(soup, r'^形象$'):
        for table in tables(nodes):
            direct = rows(table)
            if not direct or 'Pokémon HOME' not in text(direct[0]):
                continue
            images = {}
            for row in direct:
                for cell in cells(row):
                    for image in cell.find_all('img'):
                        src = image.get('data-src') or image.get('src', '')
                        filename = re.search(r'HOME_\d+[^/]*\.(?:png|webp)', unquote(src))
                        if not filename:
                            continue
                        images.setdefault(filename[0], (urljoin(url, src), text(cell.find('small')) or '通常形态'))
            # Some species lay out many normal rows followed by many shiny rows.
            # Pair only filenames explicitly present in the same HOME table.
            for filename, left in images.items():
                if '_s.' in filename:
                    continue
                right = images.get(filename.replace('.', '_s.', 1))
                if right:
                    result.append({'game': 'Pokémon HOME', 'form': left[1], 'normal_source_url': left[0], 'shiny_source_url': right[0]})
    return result


def parse_details(soup, url):
    pairs = shiny_pairs(soup, url)
    labels = {}
    for pair in pairs:
        match = re.search(r'HOME_(\d+)([^/.]*)\.', unquote(pair['normal_source_url']))
        if match:
            labels[str(int(match[1])) + match[2]] = pair['form']
    locations = acquisition(soup)
    for entry in locations:
        code = entry['form'].removeprefix('形态 ')
        match = re.fullmatch(r'(\d+)(\D*)', code)
        if match:
            entry['form'] = labels.get(str(int(match[1])) + match[2], '通常形态' if not match[2] else entry['form'])
    return {'base_stats': base_stats(soup), 'acquisition': locations, 'matchups': matchups(soup), 'movesets': movesets(soup), 'shiny_pairs': pairs}
