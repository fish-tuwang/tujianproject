"""Curated original stickers and bounded Wan image generation."""
import asyncio
import base64
from io import BytesIO
import json
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from PIL import Image
from .engagement import picture_key


def image_segment(data):
    if not data or len(data) > 5 * 1024 * 1024:
        raise ValueError('image size limit')
    with Image.open(BytesIO(data)) as image:
        if image.width * image.height > 16000000:
            raise ValueError('image dimensions limit')
        image.verify()
    return {'type': 'image', 'data': {'file': 'base64://' + base64.b64encode(data).decode()}}


class ChatImages:
    def __init__(self, api, downloads, model='wan2.6-t2i', root=None):
        self.api, self.downloads, self.model = api, downloads, model
        self.root = root or Path(__file__).with_name('qq_stickers')
        self.entries = {x['id']: x for x in json.loads((self.root / 'index.json').read_text(encoding='utf-8'))['entries']}
        self.keys={key:picture_key((self.root / entry['file']).read_bytes()) for key,entry in self.entries.items()}
        self.catalog = [{'id': x['id'], 'description': x['description'], 'tags': x['tags']} for x in self.entries.values()]

    async def select(self, decision, excluded=()):
        entry = self.entries.get(str(decision.get('sticker_id', '')))
        if entry:
            key=str(decision.get('sticker_id'))
            if self.keys[key] in excluded:
                family=entry.get('family')
                choices=[r for i,r in self.entries.items() if family and r.get('family')==family and self.keys[i] not in excluded]
                if not choices:
                    choices=[r for i,r in self.entries.items() if family and r.get('family')==family and self.keys[i] not in excluded[:1]]
                    choices.sort(key=lambda r:excluded.index(self.keys[r['id']]) if self.keys[r['id']] in excluded else 999,reverse=True)
                if not choices:return None
                entry=choices[0]
            return image_segment((self.root / entry['file']).read_bytes())
        prompt = decision.get('image_prompt')
        if not isinstance(prompt, str) or not prompt.strip():
            return None
        response = await self.api.post('/api/v1/services/aigc/image-generation/generation',
            headers={'X-DashScope-Async': 'enable'}, json={
                'model': self.model,
                'input': {'messages': [{'role': 'user', 'content': [{'text': prompt[:800]}]}]},
                'parameters': {'size': '1280*1280', 'n': 1, 'prompt_extend': False, 'watermark': False}})
        response.raise_for_status()
        task = response.json()['output']['task_id']
        if not isinstance(task, str) or not all(c.isalnum() or c == '-' for c in task):
            raise ValueError('invalid image task')
        for _ in range(30):
            await asyncio.sleep(2)
            result = await self.api.get('/api/v1/tasks/' + task)
            result.raise_for_status()
            output = result.json()['output']
            if output['task_status'] in {'FAILED', 'CANCELED', 'UNKNOWN'}:
                raise ValueError('image task failed')
            if output['task_status'] != 'SUCCEEDED':
                continue
            url = [x['image'] for x in output['choices'][0]['message']['content'] if 'image' in x][0]
            parsed = urlsplit(url)
            if parsed.scheme != 'https' or not (parsed.hostname or '').endswith('.aliyuncs.com') or parsed.username or parsed.password:
                raise ValueError('untrusted image result host')
            data = bytearray()
            async with self.downloads.stream('GET', url) as download:
                download.raise_for_status()
                async for chunk in download.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > 5 * 1024 * 1024:
                        raise ValueError('image size limit')
            return image_segment(data)
        raise ValueError('image generation timeout')
