import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import sys
from urllib.parse import urlsplit
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.acceptance import Blocked, load_environment


def source_policy():
    value=(ROOT/'docs/source-policy.md').read_text(encoding='utf-8')
    match=re.search(r'```json\s*(.*?)\s*```',value,re.S)
    return json.loads(match[1]) if match else {}


def validate_release(config,evidence=False):
    reasons=[]
    if not (ROOT/'requirements.lock').is_file():reasons.append('Python dependency lock is missing')
    if not (ROOT/'package-lock.json').is_file():reasons.append('Node dependency lock is missing')
    if config.get('mode')=='production':
        if not re.fullmatch(r'wx[0-9a-fA-F]{16}',config.get('WECHAT_APP_ID','')):reasons.append('real WeChat AppID is not configured')
        url=urlsplit(config.get('PUBLIC_API_BASE_URL',''))
        if url.scheme!='https' or not url.hostname:reasons.append('HTTPS API domain is not configured')
        else:
            try:ipaddress.ip_address(url.hostname);reasons.append('API hostname cannot be a bare IP address')
            except ValueError:
                if url.hostname=='localhost' or url.hostname.endswith('.test'):reasons.append('production domain cannot be localhost or test')
        policy=source_policy()
        if any(p.get('text')!='approved' for p in policy.values()):reasons.append('source text reuse evidence is pending')
        if not config.get('PUBLIC_IMAGE_BASE_URL','').startswith('https://'):reasons.append('real HTTPS image delivery is not configured')
        if evidence:
            if not config.get('WECHAT_CLI_PATH') or not Path(config['WECHAT_CLI_PATH']).is_file():reasons.append('WeChat developer tool is not available')
            manifest=ROOT/'artifacts/miniprogram-manifest.json'
            result=ROOT/'artifacts/acceptance/wechat-production.json'
            if not manifest.is_file() or not result.is_file():reasons.append('current-build WeChat verification is missing')
            else:
                expected=json.loads(manifest.read_text(encoding='utf-8'))
                actual=json.loads(result.read_text(encoding='utf-8'))
                if actual.get('status')!='pass' or actual.get('build_hash')!=expected.get('build_hash'):reasons.append('WeChat evidence is failed or stale')
            coverage=ROOT/'artifacts/acceptance/server/acceptance-production-readonly-coverage.json'
            if not coverage.is_file() or json.loads(coverage.read_text(encoding='utf-8')).get('status')!='pass':reasons.append('live full coverage evidence is missing')
    return reasons


def prepare_client(config):
    destination=ROOT/'artifacts/miniprogram'
    destination.mkdir(parents=True,exist_ok=True)
    for source in (ROOT/'miniprogram').rglob('*'):
        relative=source.relative_to(ROOT/'miniprogram')
        if 'tests' in relative.parts or source.suffix not in {'.js','.json','.wxml','.wxss','.png'}:continue
        target=destination/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
    project=json.loads((destination/'project.config.json').read_text(encoding='utf-8'))
    project['appid']=config.get('WECHAT_APP_ID') or 'touristappid'
    project['setting']['urlCheck']=config.get('mode')=='production'
    (destination/'project.config.json').write_text(json.dumps(project,ensure_ascii=False,indent=2),encoding='utf-8')
    base=config.get('PUBLIC_API_BASE_URL') or 'http://127.0.0.1:8092'
    value={key:{'apiBaseUrl':base} for key in ['develop','trial','release']}
    (destination/'config.js').write_text('const config = '+json.dumps(value)+';\nmodule.exports = { getConfig: version => config[version || "develop"] };\n',encoding='utf-8')
    digest=hashlib.sha256()
    for file in sorted(destination.rglob('*')):
        if file.is_file():digest.update(str(file.relative_to(destination)).encode());digest.update(file.read_bytes())
    manifest={'build_hash':digest.hexdigest(),'appid':project['appid'],'api_domain':base}
    (ROOT/'artifacts/miniprogram-manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
    return manifest


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--env-file');parser.add_argument('--mode',choices=['local','production'],default='local');parser.add_argument('--prepare-client',action='store_true');args=parser.parse_args()
    try:
        load_environment(args.env_file);config={**os.environ,'mode':args.mode}
        reasons=validate_release(config,evidence=not args.prepare_client)
        if reasons:print(json.dumps({'status':'blocked','reasons':reasons}));return 2
        value=prepare_client(config) if args.prepare_client else {}
        print(json.dumps({'status':'pass','mode':args.mode,**value}));return 0
    except Exception as error:
        print(json.dumps({'status':'fail','error':type(error).__name__}));return 1


if __name__=='__main__':raise SystemExit(main())
