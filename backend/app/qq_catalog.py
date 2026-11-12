"""Read-only catalog replies; all facts and images come from existing API rows."""
import base64
from io import BytesIO
import re

import httpx
from PIL import Image

CATEGORIES = {'tomica': '多美卡', 'pokemon': '宝可梦', 'gunpla': '高达'}
PREFIX = re.compile(r'^(多美卡|tomica|宝可梦|宝可夢|pokemon|高达|高達|gunpla)\s*[:：]?\s*', re.I)
KINDS = {'多美卡': 'tomica', 'tomica': 'tomica', '宝可梦': 'pokemon', '宝可夢': 'pokemon', 'pokemon': 'pokemon', '高达': 'gunpla', '高達': 'gunpla', 'gunpla': 'gunpla'}
HELP = '可以@我发送：\n多美卡 Mark X\n宝可梦 皮卡丘\n高达 飞翼\n多个结果可@回复序号、下一页或上一页。'
FIELDS = {'能使用的招式学习器': 'machine', '招式学习器': 'machine', '学会的招式': 'learn', '种族值': 'stats', '获得方式': 'acquisition', '获取方式': 'acquisition', '属性相性': 'matchups', '学习器': 'machine', '技能': 'learn', '招式': 'learn', '异色': 'shiny'}


def parse_query(text):
    text = re.sub(r'^(?:请|帮我)?(?:查一下|找一下|查询|搜索|查找|找)\s*', '', text.strip(), count=1)
    match = PREFIX.match(text)
    kind = KINDS[match[1].lower()] if match else None
    if match:
        text = text[match.end():]
    field = 'info'
    for word, value in FIELDS.items():
        if text.endswith(word):
            text, field = text[:-len(word)].rstrip(' 的'), value
            kind = kind or 'pokemon'
            break
    text = re.sub(r'(?:的)?(?:图鉴|详情|资料)$', '', text).strip()
    return kind, text, field


def name_of(kind, row):
    return str(row.get('name_display') or row.get('name_original') or row.get('name_zh') or row.get('name') or '名称未整理')[:180]


def hit(kind, row):
    return {'kind': kind, 'id': str(row['dex'] if kind == 'pokemon' else row['id']),
            'name': name_of(kind, row)}


def text_reply(text):
    return [{'type': 'text', 'data': {'text': text}}]


class CatalogReplies:
    def __init__(self, client, store, public_base):
        self.client, self.store, self.public_base = client, store, public_base.rstrip('/')

    async def get(self, path, params=None):
        response = await self.client.get(path, params=params)
        response.raise_for_status()
        return response.json()

    async def search(self, kind, term):
        params = {'q': term, 'limit': 100}
        if kind in {'tomica', 'gunpla'}:
            params['page'] = 1
        if kind == 'gunpla':
            params['mode'] = 'series'  # Include both regular and limited products.
            match = re.match(r'^(MG\s*Ver\.?\s*Ka|ENTRY\s*GRADE|HG|RG|MGSD|MGEX|MG|PG|EG)(?:\s+|$)', term, re.I)
            if match:
                grade = re.sub(r'\W', '', match[1]).casefold().replace('entrygrade', 'eg')
                metadata = await self.get('/api/gunpla/filters')
                brand = next((b for b in metadata['brands'] if re.sub(r'\W', '', b['name']).casefold().replace('entrygrade', 'eg') == grade), None)
                if brand:
                    params.update(mode='grade', grade=brand['id'], q=term[match.end():].strip())
        body = await self.get('/api/' + kind, params)
        return [hit(kind, row) for row in body['items']], body.get('total', len(body['items']))

    async def reply(self, group, user, text):
        if text in {'帮助', '菜单', 'help', '图鉴'} or not text:
            return text_reply(HELP)
        context = self.store.context(group, user)
        if text.isdigit() and context and 1 <= int(text) <= len(context['items']):
            selected = context['items'][int(text) - 1]
            return await self.detail(selected, context['field'])
        if text in {'下一页', '上一页'}:
            if not context:
                return text_reply('候选列表已过期，请重新@我发送名称查询。')
            context['page'] = max(0, min((len(context['items']) - 1) // 5, context['page'] + (1 if text == '下一页' else -1)))
            self.store.save_context(group, user, context)
            return text_reply(self.candidates(context))
        kind, term, field = parse_query(text)
        if not term or len(term) > 100:
            return text_reply(HELP)
        items, total = [], 0
        for category in [kind] if kind else CATEGORIES:
            rows, count = await self.search(category, term)
            items.extend(rows)
            total += count
        if not items:
            self.store.clear_context(group, user)
            return text_reply('没有找到“' + term + '”，可以换中文/英文名称或编号再试。')
        if len(items) == 1:
            self.store.clear_context(group, user)
            return await self.detail(items[0], field)
        context = {'items': items, 'total': total, 'page': 0, 'field': field}
        self.store.save_context(group, user, context)
        return text_reply(self.candidates(context))

    @staticmethod
    def candidates(context):
        start = context['page'] * 5
        title = '找到 ' + str(context['total']) + ' 条图鉴'
        if context['total'] > len(context['items']):
            title += '（展示前' + str(len(context['items'])) + '条，可缩小关键词）'
        rows = [f'{index + 1}. [{CATEGORIES[item["kind"]]}] {item["name"]}' for index, item in enumerate(context['items'][start:start + 5], start)]
        return '\n'.join([title, *rows, f'第{context["page"] + 1}/{(len(context["items"]) + 4) // 5}页 · @我回复序号查看，或发送下一页/上一页。'])

    async def detail(self, item, field='info'):
        kind, identity = item['kind'], item['id']
        path = '/api/' + kind + ('/products/' if kind == 'gunpla' else '/') + identity
        row = await self.get(path)
        name = name_of(kind, row)
        lines, images = [f'【{CATEGORIES[kind]}】{name}'], []
        cover = row.get('preview_image_url') or row.get('cover')
        if cover:
            images.append(cover)
        if kind == 'tomica':
            for label, key in [('编号', 'number'), ('品牌', 'brand'), ('发售年份', 'release_year'), ('比例', 'scale'), ('系列', 'series')]:
                if row.get(key):
                    lines.append(label + '：' + str(row[key]))
            lines.append('收录版本：' + str(len(row.get('variants', []))))
            link = '/preview/?catalog=tomica#tomica/' + identity
        elif kind == 'gunpla':
            for label, key in [('官方价格', 'price_cny_text'), ('日本价格', 'price_jpy_text'), ('发售日期', 'release_text')]:
                lines.append(label + '：' + str(row.get(key) or '未公布'))
            lines.append('图库：' + str(len(row.get('gallery', []))) + ' 张 · 详细图：' + str(len(row.get('detail_images', []))) + ' 张')
            link = '/preview/gunpla.html#product/' + identity
        else:
            lines.extend(['全国编号：#' + identity.zfill(4), '属性：' + ' / '.join(row.get('types', []))])
            extra = row.get('extra') or {}
            if field in {'info', 'stats'}:
                for group in (extra.get('base_stats') or [])[:3]:
                    lines.append(group['label'] + '：' + ' / '.join(str(s['name']) + ' ' + str(s['value']) for s in group['stats']) + ' · 合计 ' + str(group['total']))
            elif field == 'shiny':
                pairs = extra.get('shiny_pairs') or []
                if pairs:
                    images = [p.get('preview_image_url') for p in [pairs[0]['normal'], pairs[0]['shiny']] if p.get('preview_image_url')]
                    lines.append('图片顺序：通常配色 → 异色')
                else:
                    lines.append('暂无异色对照资料。')
            else:
                lines.extend(self.pokemon_extra(extra, field))
            link = '/preview/?catalog=pokemon#pokemon/' + identity
        lines.append('详情：' + self.public_base + link)
        segments = text_reply('\n'.join(lines)[:3500])
        for image in images[:2]:
            segment = await self.image(image, kind)
            if segment:
                segments.append(segment)
        return segments

    @staticmethod
    def pokemon_extra(extra, field):
        if field == 'acquisition':
            return [f'{r["games"]} · {r.get("form") or "通常形态"}：{r["location"]} {r.get("method") or ""}' for r in (extra.get('acquisition') or [])[:5]] or ['暂无获得方式资料。']
        if field == 'matchups':
            return [str(g['label']) + '：' + ' / '.join(str(r['name']) + ' ×' + str(r['multiplier']) for r in g.get('types', [])) for g in (extra.get('matchups') or [])[:2]] or ['暂无属性相性资料。']
        groups = [g for g in extra.get('movesets', []) if g.get('kind') == field]
        return [str(g['game']) + ' · ' + str(g['form']) + ' · ' + str(g['method']) + '：' + '、'.join(str(r['name']) for r in g.get('moves', [])[:12]) for g in groups[:2]] or ['暂无对应招式资料。']

    async def image(self, path, kind):
        # Never forward catalog credentials to a supplied absolute or third-party URL.
        if not re.fullmatch(r'/api/reference-images/[0-9a-fA-F-]{36}', str(path)):
            return None
        path += '/display?width=480' if kind == 'gunpla' else ''
        try:
            async with self.client.stream('GET', path) as response:
                response.raise_for_status()
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > 6 * 1024 * 1024:
                        return None
            with Image.open(BytesIO(data)) as original:
                if original.width * original.height > 20_000_000:
                    return None
                image = original.convert('RGBA')
                image.thumbnail((960, 960))
                background = Image.new('RGB', image.size, 'white')
                background.paste(image, mask=image.getchannel('A'))
                output = BytesIO()
                background.save(output, 'JPEG', quality=88)
            return {'type': 'image', 'data': {'file': 'base64://' + base64.b64encode(output.getvalue()).decode()}}
        except (httpx.HTTPError, OSError, ValueError, Image.DecompressionBombError):
            return None
