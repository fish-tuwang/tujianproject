"""Retry only the fixture-verified source pages covered by newly added real fixtures."""
import json
from pathlib import Path
import subprocess

names=['tba006.html','tba036.html','tba121.html','tbal-1.html','tbas01.html','tbas1.html','tbas11.html','tbas31.html']
urls=','.join("'http://tomica.minibird.jp/t-tomica/number/"+name+"'" for name in names)
args=['runuser','-u','postgres','--','/www/server/pgsql/bin/psql','-d','dual_catalog','-X','-v','ON_ERROR_STOP=1','-At']
urls += ",'http://tomica.minibird.jp/t-tomica/special/tto%20V%E3%83%BBfa-ren.html'"
condition="status IN ('failed','isolated') AND url IN ("+urls+") AND run_id IN (SELECT id FROM sync_runs WHERE source='tomica' AND status='running')"
previous=subprocess.run(args,input='SELECT coalesce(json_agg(row_to_json(t)),\'[]\'::json) FROM (SELECT id,url,status,issues FROM sync_items WHERE '+condition+') t;',text=True,capture_output=True,check=True)
path=Path('/opt/dual-catalog/backups/source-repair-before-014.json')
if not path.exists():path.write_text(previous.stdout);path.chmod(0o600)
result=subprocess.run(args,input="UPDATE sync_items SET status='pending',next_retry_at=NULL WHERE "+condition+';',text=True,capture_output=True,check=True)
print(result.stdout)
