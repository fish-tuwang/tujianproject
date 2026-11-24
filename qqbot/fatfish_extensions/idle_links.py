"""Visible-link filtering for proactive messages only."""
import re

# Only visible text is filtered; image transport URLs are not chat links.
IDLE_LINK = re.compile(r"(?:[a-z][a-z0-9+.-]*\\?:/{1,2}|www\.|(?<![\w@])(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+(?:[a-z]{2,63}|xn--[a-z0-9-]+)\b)[^\s<>\u3000，。！？；、）】]*", re.I)


def idle_without_links(message):
 """Remove visible links and rich link cards from unsolicited bubbles only."""
 if isinstance(message,str):
  message=re.sub(r'\[CQ:[^\]]*\]','',message)
  message=re.sub(r'\[([^\]]+)\]\([^)]*\)',r'\1',message)
  return IDLE_LINK.sub('',message).strip()
 if not isinstance(message,list):return []
 result=[]
 for segment in message:
  if not isinstance(segment,dict):continue
  kind=segment.get('type')
  if kind=='text':
   text=idle_without_links(str(segment.get('data',{}).get('text','')))
   if text:result.append({**segment,'data':{**segment.get('data',{}),'text':text}})
  elif kind in {'image','face','at','reply','record'}:result.append(segment)
 # Reply/mention segments alone must not become an empty unsolicited message.
 return result if any(s.get('type') in {'text','image','face','record'} for s in result) else []
