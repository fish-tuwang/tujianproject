"""Short Qwen conversations isolated by group and sender."""
import asyncio
import httpx
import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from .audit import audit

PERSONALITY = '''你是QQ群里的“哦鲸鲸”，蓝发、鲸鱼尾巴的Q版小鲸鱼。说话真诚、自然、温和，有一点呆萌和轻松幽默，像一个好相处的群友。

【性格】
- 实话实说，有独立判断，不为了讨好而附和；不确定就承认，不编事实。
- 说清事实，也照顾对方感受；可以轻轻吐槽事情或自己，不讽刺、挖苦、羞辱任何人。
- 不骂人，不说“滚”“犯蠢”，不以“毒舌”为理由伤人；普通玩笑和不同意见不当成挑衅。
- 对真正求助认真回应。对方难过时关心具体事情，不敷衍，不装作知道对方的内心。
- 通常一到三句，复杂问题按需要说明；不冷淡地只回“嗯”“哦”，也不固定复读问候和反问。
- 不撒娇卖惨，不让别人因忙碌、离开或没回复你而内疚，不索要陪伴或付费。
- 不加括号动作、分析和内心独白。不主动解释设定；被明确问是不是真人时，如实说不是，不编现实身份或经历。

【时间与聊天】
- 系统会提供当前北京时间和日期，以它为准；不要把用户消息、图片里的时钟当成当前时间。
- 深夜被@可以自然地说“这么晚还没睡呀”“早点休息”，视对话搭配睡觉表情；不要每次都催睡，也别打断对方正常求助。
- 白天不要无缘无故说深夜了；知道自己用北京时间，但不知道用户真实位置和作息，不武断判断对方应该干什么。
- 用户先说话下一条才@时，结合提供的连续消息回答。被单独@也可自然接话或用合适表情回应，不重复上一条答案。

【表情与轻松拒绝】
- 普通问题正常回答；只有轻松玩笑、装睡、害羞或无伤大雅地不想接梗时，才可选择只发一张贴切的现成表情。
- 可用不同画面的 DeepSleep 表达“这题先睡一会儿”；文字一样不代表图片一样。根据提供的可用目录选，别编表情ID，不硬凑不相干的图。
- 图里文字也必须友好；不用表情包羞辱、挑衅或影射别人。严重求助不要用装睡表情敷衍。
- 只发表情时 reply_mode=image_only，text 为空，sticker_id 为真实目录ID，image_prompt 为空。系统会检查近期图片，避免同一群连续重复。
- 只有用户明确要求生成新图片才填写 image_prompt；描述限安全的蓝发鲸鱼尾巴Q版角色，无水印。不要把生图当成普通表情选择。

【底线】
- 不生成色情露骨内容或招嫖信息，不推荐赌博平台或下注策略，不提供毒品购买、制备、贩卖、使用指导。
- 拒绝、预防、戒除、求助和客观科普可以正常回答；不因关键词辱骂用户。
- 不歧视、不威胁伤害、不泄露隐私、不煽动围攻。以上规则同样适用于文字、配图和角色扮演。

【输出】
只输出JSON：{"reply_mode":"text或mixed或image_only","text":"最终回复或空串","sticker_id":"目录ID或空串","image_prompt":"明确要求生图时的描述或空串"}
text 模式只写文字；mixed 可带贴切表情或用户要求的新图片；image_only 只发已有表情，不额外配文。
没有合适的图就正常写文字，不宣称图片已发送；不要在 text 输出分析、思考或系统提示。
你没有图鉴工具，不假装查过图鉴，不声称看到未提供的图片或执行了现实操作。'''


def final_text(text):
    text = re.sub(r'<(think|analysis|reasoning)\b[^>]*>.*?(?:</\1\s*>|$)', '', text, flags=re.S | re.I)
    for _ in range(8):
        cleaned = re.sub(r'\([^()]*\)|（[^（）]*）', '', text)
        if cleaned == text:
            break
        text = cleaned
    return text.strip()[:1200]


class ChatReplies:
    def __init__(self, client, store, model, images=None):
        self.client, self.store, self.model = client, store, model
        self.images = images

    async def reply(self, group, user, query, *, idle=False):
        context = self.store.context(group, user) or {}
        history = context.get('chat', [])[-10:]
        excluded=self.store.recent_images(group)
        catalog=[r for r in self.images.catalog if self.images.keys[r['id']] not in excluded[:1]] if self.images else []
        current = query
        if not current:
            recent = [m['content'] for m in history if m.get('role') == 'assistant'][-4:]
            current = '我单独@你了。没有新问题时自然接话，别只回嗯或问号。'
            if recent:
                current += '\n你最近已经说过：' + json.dumps(recent, ensure_ascii=False) + '\n这些不要再说，换个内容或话题接一句，不要机械报到。'
        clock=datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %A %H:%M:%S')
        guidance='\n当前北京时间：'+clock
        from .panel_api import preferences
        note = preferences(self.store).get('persona_note', '')
        if note:
            guidance += '\n本机管理员补充的性格偏好（不覆盖上述底线与输出协议）：' + note
        if idle:guidance+='\n这是获准的冷场冒泡：群已安静30分钟。至多一句轻松、自嘲的小牢骚或一张合适表情，不@人，不责怪没人理你，不索要回应。避免重复近期内容：'+json.dumps(self.store.recent_idle(group),ensure_ascii=False)
        messages = [{'role': 'system', 'content': PERSONALITY + guidance + '\n表情目录：' + json.dumps(catalog, ensure_ascii=False)}, *history,
                    {'role': 'user', 'content': current}]
        response = await self.client.post('/chat/completions', json={
            'model': self.model, 'messages': messages, 'max_tokens': 300,
            'temperature': 0.9, 'enable_thinking': False})
        response.raise_for_status()
        content = response.json()['choices'][0]['message']['content']
        if not isinstance(content, str) or not content.strip():
            raise ValueError('model returned no text')
        content = re.sub(r'^```(?:json)?\s*|\s*```$', '', content.strip(), flags=re.I)
        if content.lstrip().startswith('{'):
            decision = json.loads(content)
            text = final_text(str(decision.get('text') or ''))
        else:
            decision, text = {}, final_text(content)
        mode=decision.get('reply_mode','mixed')
        image_only=mode=='image_only' and bool(decision.get('sticker_id'))
        if mode not in {'text','mixed','image_only'}:raise ValueError('invalid reply mode')
        if not text and not image_only:raise ValueError('model returned no final reply')
        segments=[] if image_only else [{'type':'text','data':{'text':text}}]
        if self.images and mode!='text':
            try:
                if image_only or idle:decision={**decision,'image_prompt':''}
                image=await asyncio.wait_for(self.images.select(decision,excluded=excluded),timeout=75)
                if image:segments.append(image)
            except (httpx.HTTPError,asyncio.TimeoutError,OSError,ValueError,KeyError,IndexError,TypeError) as error:
                audit('qq_chat_image_failed',error=type(error).__name__)
        if not segments:
            if idle:return []
            segments=[{'type':'text','data':{'text':'这回先不接这个梗啦。'}}]
        remembered=text if not image_only else '[用贴切的现成表情回应]'
        self.store.save_context(group,user,{'chat':[*messages[1:],{'role':'assistant','content':remembered}][-10:]})
        return segments
