"""Import the project-only consistent snapshot into an empty application DB."""
from pathlib import Path
import os
import subprocess
from urllib.parse import urlsplit

root=Path('/opt/dual-catalog')
values=dict(line.split('=',1) for line in (root/'.env').read_text().splitlines() if line and not line.startswith('#') and '=' in line)
url=urlsplit(values['DATABASE_URL'])
if url.path!='/dual_catalog' or url.hostname!='127.0.0.1':raise RuntimeError('unexpected target database')
env={**os.environ,'PGPASSWORD':url.password}
base=['-h','127.0.0.1','-U','dual_catalog_app','-d','dual_catalog']
query=subprocess.run(['/www/server/pgsql/bin/psql',*base,'-Atc','SELECT (SELECT count(*) FROM tomica_models)+(SELECT count(*) FROM pokemon);'],env=env,text=True,capture_output=True,check=True)
if query.stdout.strip()!='0':raise RuntimeError('target already contains catalog data; refusing overwrite')
backup=root/'backups/before-source-import.dump'
if not backup.exists():subprocess.run(['/www/server/pgsql/bin/pg_dump',*base,'-Fc','-f',str(backup)],env=env,check=True)
backup.chmod(0o600)
result=subprocess.run(['/www/server/pgsql/bin/pg_restore',*base,'--data-only','--no-owner','--no-acl','--single-transaction',str(root/'bootstrap-data.dump')],env=env,text=True,capture_output=True)
if result.returncode:
    print(result.stderr[-1500:])
    raise RuntimeError('atomic bootstrap restore failed')
result=subprocess.run(['/www/server/pgsql/bin/psql',*base,'-Atc',"SELECT 'tomica_models='||count(*) FROM tomica_models; SELECT 'pokemon='||count(*) FROM pokemon; SELECT source||'|'||status FROM sync_runs;"],env=env,text=True,capture_output=True,check=True)
print(result.stdout)
