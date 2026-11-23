"""Private local persistence shared by the FatFish extensions."""
from contextlib import contextmanager
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
import tempfile
import threading
from zoneinfo import ZoneInfo

DATA = Path.home()/'Library/Application Support/LittleAtlasQQ/fatfish/data'
TZ = ZoneInfo('Asia/Shanghai')
_lock = threading.RLock()


def day(ts=None):
    return datetime.fromtimestamp(ts,TZ).strftime('%Y-%m-%d') if ts is not None else datetime.now(TZ).strftime('%Y-%m-%d')


def read(path, default):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return default
    # Corrupt data must never be silently replaced with an empty document.


@contextmanager
def locked(path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with _lock, path.with_suffix(path.suffix+'.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        yield


def write(path, value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd,name=tempfile.mkstemp(prefix=path.name+'.',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as stream:
            json.dump(value,stream,ensure_ascii=False,indent=1);stream.flush();os.fsync(stream.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)


def edit(name, change, default=None):
    path=DATA/name
    with locked(path):
        value=read(path,{} if default is None else default)
        result=change(value)
        write(path,value)
        return result
