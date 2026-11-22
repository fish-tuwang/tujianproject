"""Persistent per-group idle limits and visual-image history."""
import base64
import hashlib
from io import BytesIO
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from PIL import Image

TZ=ZoneInfo('Asia/Shanghai')


def picture_key(body):
 with Image.open(BytesIO(body)) as image:
  if image.width*image.height>16000000:raise ValueError('image dimensions limit')
  image=image.convert('RGBA')
  return hashlib.sha256(str(image.size).encode()+image.tobytes()).hexdigest()


def segment_key(segment):
 value=segment.get('data',{}).get('file','')
 return picture_key(base64.b64decode(value[9:])) if value.startswith('base64://') else None


def quiet(now):
 return datetime.fromtimestamp(now,TZ).hour>=22 or datetime.fromtimestamp(now,TZ).hour<9


def day(now):return datetime.fromtimestamp(now,TZ).date().isoformat()


def eligible(row,now,minutes=30,limit=3):
 if quiet(now) or not row:return False
 group,human,mention,last_idle,count_date,count,attempt=row
 return (mention>now-86400 and now-human>=minutes*60 and human>last_idle and now-last_idle>=7200 and (count_date!=day(now) or count<limit))


class EngagementStore:
 def setup_engagement(self):
  with self.connect() as db:
   db.executescript('CREATE TABLE IF NOT EXISTS group_activity(group_id TEXT PRIMARY KEY,last_human REAL NOT NULL,last_mention REAL NOT NULL DEFAULT 0,last_idle REAL NOT NULL DEFAULT 0,count_date TEXT NOT NULL DEFAULT "",idle_count INTEGER NOT NULL DEFAULT 0,last_attempt REAL NOT NULL DEFAULT 0);CREATE TABLE IF NOT EXISTS image_history(group_id TEXT,image_key TEXT,at REAL);CREATE TABLE IF NOT EXISTS idle_history(group_id TEXT,text TEXT,at REAL);')
 def note_activity(self,group,mentioned,now=None):
  now=time.time() if now is None else now
  with self.connect() as db:
   db.execute('INSERT INTO group_activity(group_id,last_human,last_mention) VALUES(?,?,?) ON CONFLICT(group_id) DO UPDATE SET last_human=excluded.last_human,last_mention=CASE WHEN ?>0 THEN excluded.last_mention ELSE group_activity.last_mention END',(group,now,now if mentioned else 0,int(mentioned)))
 def recent_images(self,group):
  with self.connect() as db:return [r[0] for r in db.execute('SELECT image_key FROM image_history WHERE group_id=? ORDER BY at DESC,rowid DESC LIMIT 3',(group,))]
 def record_image(self,group,key):
  if not key:return
  with self.connect() as db:
   db.execute('INSERT INTO image_history VALUES(?,?,?)',(group,key,time.time()));db.execute('DELETE FROM image_history WHERE group_id=? AND rowid NOT IN (SELECT rowid FROM image_history WHERE group_id=? ORDER BY at DESC,rowid DESC LIMIT 10)',(group,group))
 def activity(self,group):
  with self.connect() as db:return db.execute('SELECT * FROM group_activity WHERE group_id=?',(group,)).fetchone()
 def idle_allowed(self,group,now=None,minutes=30,limit=3):return eligible(self.activity(group),time.time() if now is None else now,minutes,limit)
 def idle_candidates(self,now=None,minutes=30,limit=3):
  now=time.time() if now is None else now
  with self.connect() as db:rows=db.execute('SELECT * FROM group_activity').fetchall()
  return [r[0] for r in rows if eligible(r,now,minutes,limit) and now-r[6]>=1800]
 def claim_idle(self,group,now=None,minutes=30,limit=3):
  now=time.time() if now is None else now
  with self.connect() as db:
   db.execute('BEGIN IMMEDIATE');row=db.execute('SELECT * FROM group_activity WHERE group_id=?',(group,)).fetchone()
   if not eligible(row,now,minutes,limit) or now-row[6]<1800:return False
   db.execute('UPDATE group_activity SET last_attempt=? WHERE group_id=?',(now,group));return True
 def record_idle(self,group,text,now=None):
  now=time.time() if now is None else now
  with self.connect() as db:
   db.execute('UPDATE group_activity SET last_idle=?,idle_count=CASE WHEN count_date=? THEN idle_count+1 ELSE 1 END,count_date=? WHERE group_id=?',(now,day(now),day(now),group))
   db.execute('INSERT INTO idle_history VALUES(?,?,?)',(group,text[:200],now));db.execute('DELETE FROM idle_history WHERE group_id=? AND rowid NOT IN (SELECT rowid FROM idle_history WHERE group_id=? ORDER BY at DESC,rowid DESC LIMIT 3)',(group,group))
 def recent_idle(self,group):
  with self.connect() as db:return [r[0] for r in db.execute('SELECT text FROM idle_history WHERE group_id=? ORDER BY at DESC LIMIT 3',(group,))]


def activity_target(event,settings):
 if not isinstance(event,dict) or event.get('post_type')!='message' or event.get('message_type')!='group' or str(event.get('self_id'))!=settings.account or str(event.get('user_id'))==settings.account or event.get('anonymous'):return None
 group=str(event.get('group_id',''));user=str(event.get('user_id',''))
 if not group.isdecimal() or not user.isdecimal() or not isinstance(event.get('message'),list):return None
 if settings.allowed_groups!='*' and group not in [v.strip() for v in settings.allowed_groups.split(',')]:return None
 return group,any(isinstance(r,dict) and r.get('type')=='at' and str((r.get('data') or {}).get('qq'))==settings.account for r in event['message'])


def batches(segments,message=''):
 text=[s for s in segments if s.get('type')=='text' and s.get('data',{}).get('text','').strip()];images=[s for s in segments if s.get('type')=='image']
 result=[]
 if text:result.append(([{'type':'reply','data':{'id':message}}] if message else [])+text)
 result.extend([[s] for s in images]);return result
