"""Install repository-owned implementations over public stubs, without editing upstream."""
import importlib
from pathlib import Path
import sys

from . import common,memory,mood,soul,relation,usage

VERSION='1.0.0'


def install(bot_directory):
    bot_directory=Path(bot_directory)
    sys.path.insert(0,str(bot_directory))
    common.DATA=(bot_directory/'data').resolve()
    common.DATA.mkdir(parents=True,exist_ok=True,mode=0o700)
    for name,implementation in [('memory',memory),('mood2',mood),('soul',soul),('galgame',relation)]:
        target=importlib.import_module(name)
        # Keep native module identities: bot/control/panel import the same objects.
        for key,value in vars(implementation).items():
            if key not in {'__name__','__file__','__package__','__spec__','__loader__','__builtins__','common','memory','mood','json','re','time','math','hashlib','unicodedata'}:
                setattr(target,key,value)
        target.STUB=False
    usage.install(bot_directory)
    return VERSION
