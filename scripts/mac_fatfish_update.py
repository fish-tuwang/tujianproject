"""Install and update the public FatFish runtime independently of private settings."""
import argparse
import fcntl
import io
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tarfile
import time

ROOT = Path.home() / 'Library/Application Support/LittleAtlasQQ/fatfish'
UPSTREAM = 'https://github.com/Vegra85/fatfish-bot.git'
LABEL = 'com.little-atlas.fatfish-updater'


def run(args, timeout=120, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, timeout=timeout, **kwargs).stdout


def extract(body, target):
    if len(body) > 64 * 1024 * 1024: raise ValueError('archive too large')
    with tarfile.open(fileobj=io.BytesIO(body)) as archive:
        for entry in archive:
            path = Path(entry.name)
            if path.is_absolute() or '..' in path.parts or not (entry.isfile() or entry.isdir()):
                raise ValueError('unsafe upstream archive')
            if entry.size > 16 * 1024 * 1024: raise ValueError('upstream file too large')
            if entry.isdir(): (target/path).mkdir(parents=True, exist_ok=True)
            else:
                (target/path).parent.mkdir(parents=True, exist_ok=True)
                (target/path).write_bytes(archive.extractfile(entry).read())


def check(root=ROOT):
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (root/'update.lock').open('w') as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: return
        repo = root/'upstream.git'
        if not repo.exists(): run(['git','init','--bare',str(repo)])
        git = ['git','--git-dir='+str(repo)]
        run(git+['-c','http.lowSpeedLimit=1024','-c','http.lowSpeedTime=20','fetch','--quiet',UPSTREAM,'main'], timeout=90)
        revision = run(git+['rev-parse','FETCH_HEAD']).decode().strip()
        current = root/'current'
        previous = current.resolve() if current.is_symlink() else None
        if previous and previous.name == revision:
            print('FATFISH_UP_TO_DATE', revision[:12], flush=True); return
        release = root/'releases'/revision
        if release.exists(): shutil.rmtree(release)
        release.mkdir(parents=True)
        extract(run(git+['archive','--format=tar',revision]), release)
        for required in ['bot/bot.py','bot/panel.py','bot/panel.html','requirements.txt','LICENSE']:
            if not (release/required).is_file(): raise ValueError('incomplete upstream')
        # New unrecognised dependencies require adapter work instead of breaking a live bot.
        permitted = {'httpx','websockets','tzdata','pillow'}
        import re
        for line in (release/'requirements.txt').read_text().splitlines():
            line = line.split('#')[0].strip()
            if line and re.split(r'[<=>~!\[;\s]',line)[0].lower() not in permitted:
                raise ValueError('new upstream dependency needs deployment assessment')
        # Each release owns its dependencies: rolling back code also restores its venv.
        run([str(root/'venv/bin/python'),'-m','venv',str(release/'venv')], timeout=60)
        python = release/'venv/bin/python'
        run([str(release/'venv/bin/pip'),'install','-q','--cert',str(root/'system-ca.pem'),'-r',str(release/'requirements.txt'),
             'python-pptx','imageio-ffmpeg','yt-dlp'], timeout=180)
        for name in ['config.json','persona.md','data','stickers']:
            target = release/'bot'/name
            if target.exists():
                if target.is_dir(): shutil.rmtree(target)
                else: target.unlink()
            target.symlink_to(root/name, target_is_directory=name in {'data','stickers'})
        run([str(python),'-m','compileall','-q',str(release/'bot')], timeout=60)
        probe="import sys;sys.path.insert(0,sys.argv[2]);from fatfish_extensions import install;install(sys.argv[1]);import bot,panel;assert callable(bot.main) and callable(panel.serve) and not bot.memory.STUB"
        run([str(python),'-c',probe,str(release/'bot'),str(root/'extensions/current')], timeout=40)
        link = root/'next'
        link.unlink(missing_ok=True); link.symlink_to(release); link.replace(current)
        env_link=root/'venv-next';env_link.unlink(missing_ok=True);env_link.symlink_to(release/'venv');env_link.replace(root/'venv')
        domain = 'gui/' + str(os.getuid()) + '/'
        try:
            for label in ['com.little-atlas.fatfish','com.little-atlas.fatfish-panel']:
                run(['launchctl','kickstart','-k',domain+label], timeout=15)
            deadline = time.monotonic()+50
            import urllib.request
            while True:
                try:
                    with urllib.request.urlopen('http://127.0.0.1:8765/api/overview', timeout=5) as response:
                        data = json.load(response)
                    if data.get('bot') == 'online' and data.get('qq',{}).get('state') == 'ok':break
                except Exception: pass
                if time.monotonic() > deadline: raise RuntimeError('updated runtime failed health check')
                time.sleep(2)
        except Exception:
            if previous:
                link.unlink(missing_ok=True);link.symlink_to(previous);link.replace(current)
                env_link.unlink(missing_ok=True);env_link.symlink_to(previous/'venv');env_link.replace(root/'venv')
                for label in ['com.little-atlas.fatfish','com.little-atlas.fatfish-panel']:
                    subprocess.run(['launchctl','kickstart','-k',domain+label],capture_output=True)
            raise
        (root/'revision.json').write_text(json.dumps({'revision':revision,'previous':previous.name if previous else None,'verified_at':time.time()}))
        print('FATFISH_UPDATED',revision[:12],flush=True)


def install(root=ROOT):
    shutil.copy2(__file__,root/'updater.py')
    agent = Path.home()/'Library/LaunchAgents'/f'{LABEL}.plist'
    agent.write_bytes(plistlib.dumps({'Label':LABEL,'ProgramArguments':[sys.executable,str(root/'updater.py')],
        'RunAtLoad':True,'StartInterval':300,'EnvironmentVariables':{'PATH':'/Applications/Docker.app/Contents/Resources/bin:/usr/local/bin:/usr/bin:/bin','GIT_TERMINAL_PROMPT':'0'},
        'StandardOutPath':str(root/'updater.log'),'StandardErrorPath':str(root/'updater-errors.log')}))
    domain='gui/'+str(os.getuid())
    subprocess.run(['launchctl','bootout',domain,str(agent)],capture_output=True)
    run(['launchctl','bootstrap',domain,str(agent)])


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--install',action='store_true');args=parser.parse_args()
    try:
        if args.install:install()
        else:check()
    except Exception as error:
        print('FATFISH_UPDATE_FAILED',type(error).__name__,flush=True);sys.exit(1)
