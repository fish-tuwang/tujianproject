"""Local tools for the official dsh-qqbot plugin; no NapCat credentials or APIs."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import random
import sqlite3
import time
from zoneinfo import ZoneInfo


def choose(root, family, conversation='global'):
    entries = json.loads((root/'stickers/index.json').read_text())['entries']
    entries = [r for r in entries if r.get('family') == family]
    if not entries: raise ValueError('no suitable sticker')
    with sqlite3.connect(root/'sticker-history.sqlite3') as db:
        db.execute('CREATE TABLE IF NOT EXISTS choices(place TEXT,key TEXT,at REAL)')
        db.execute('BEGIN IMMEDIATE')
        recent = [r[0] for r in db.execute('SELECT key FROM choices WHERE place=? ORDER BY at DESC LIMIT 3',(conversation,))]
        candidates = [r for r in entries if r['fingerprint'] not in recent]
        if not candidates:candidates = [r for r in entries if not recent or r['fingerprint'] != recent[0]]
        if not candidates: return {'ok':False,'reason':'no non-repeating suitable image'}
        selected = random.choice(candidates)
        path = (root/'stickers'/selected['file']).resolve()
        if path.parent != (root/'stickers').resolve() or not path.is_file():raise ValueError('invalid asset')
        db.execute('INSERT INTO choices VALUES(?,?,?)',(conversation,selected['fingerprint'],time.time()))
        db.execute('DELETE FROM choices WHERE at<?',(time.time()-7*86400,))
    return {'ok':True,'id':selected['id'],'file_path':str(path),'description':selected['description']}


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--pick');parser.add_argument('--conversation',default='global');args=parser.parse_args()
    now=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds')
    value={'beijing_time':now}
    if args.pick:value.update(choose(Path(__file__).resolve().parent,args.pick,args.conversation))
    print(json.dumps(value,ensure_ascii=False))
