"""Apply owner-authenticated panel API routing without replacing the relay."""
import argparse
from pathlib import Path
import re
import shutil
import subprocess
import time

MARKER='        # Owner-authenticated QQ panel writes: scoped endpoints only'


def render_config(text):
    # Upgrade the previous two exact write routes; preserve all unrelated routes.
    text=re.sub(r'        # Owner-authenticated QQ panel writes: scoped endpoints only\n(?:        location = /qq-panel/api/(?:send|music/login) \{.*?^        \}\n)+','',text,flags=re.S|re.M)
    if '        # Owner-authenticated QQ panel management API' in text:return text
    ssl=text.index('listen 443 ssl;')
    targets=re.findall(r'proxy_pass\s+([^;]+);',text[ssl:])
    if not targets:raise ValueError('Cannot identify current catalog upstream')
    upstream=targets[-1]
    if not re.fullmatch(r'(?:\$[a-zA-Z_][a-zA-Z0-9_]*|http://127\.0\.0\.1:[0-9]+)',upstream):raise ValueError('Unexpected upstream')
    blocks=['        # Owner-authenticated QQ panel management API\n        location ^~ /qq-panel/api/ {\n            if (-f /var/run/dual-catalog-gates/maintenance) { return 503; }\n            if ($catalog_known_crawler) { return 403; }\n            limit_except GET HEAD POST { deny all; }\n            client_max_body_size 32m;\n            proxy_pass UPSTREAM;\n            proxy_set_header Host $host;\n            proxy_set_header X-Real-IP $remote_addr;\n            proxy_set_header X-Forwarded-For $remote_addr;\n            proxy_set_header X-Forwarded-Proto $scheme;\n            proxy_set_header X-Catalog-Service "";\n            proxy_connect_timeout 5s;\n            proxy_read_timeout 190s;\n        }\n'.replace('UPSTREAM',upstream)]
    index=text.rfind('        location / {')
    if index<ssl:raise ValueError('SSL default route missing')
    return text[:index]+''.join(blocks)+text[index:]


def apply(path,container):
    old=path.read_text();new=render_config(old)
    if old==new:print('PANEL_PROXY_ALREADY_CONFIGURED');return
    backup=path.with_name(path.name+'.before-panel-post-'+str(int(time.time())))
    shutil.copy2(path,backup);backup.chmod(0o600)
    try:
        # The config is a Docker file bind mount; preserve the mounted inode.
        path.write_text(new)
        subprocess.run(['docker','exec',container,'nginx','-t'],check=True)
        subprocess.run(['docker','exec',container,'nginx','-s','reload'],check=True)
    except BaseException:
        path.write_text(old)
        subprocess.run(['docker','exec',container,'nginx','-s','reload'],capture_output=True)
        raise
    print('PANEL_PROXY_UPDATED_WITH_BACKUP')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--config',type=Path,default=Path('/opt/dual-catalog/preview-nginx.conf'));parser.add_argument('--container',default='dual-catalog-preview-proxy');args=parser.parse_args()
    apply(args.config,args.container)
