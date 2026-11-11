"""Private JSON event files; host logrotate owns retention and file rotation."""
from datetime import datetime, timezone
import json
import logging
from logging.handlers import WatchedFileHandler
from pathlib import Path

CHANNELS = {'collection', 'deploy'}


class EventFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({'time': datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec='milliseconds'), 'event': record.audit_event, **record.audit_fields}, ensure_ascii=False, separators=(',', ':'), default=str)


def configure_audit(directory, channels=CHANNELS):
    directory = Path(directory)
    directory.mkdir(mode=0o750, parents=True, exist_ok=True)
    for channel in channels:
        if channel not in CHANNELS:
            raise ValueError('unknown audit channel')
        logger = logging.getLogger('catalog.audit.' + channel)
        target = str((directory / (channel + '.jsonl')).resolve())
        if any(isinstance(h, WatchedFileHandler) and h.baseFilename == target for h in logger.handlers):
            continue
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
            handler.close()
        Path(target).touch(mode=0o640, exist_ok=True)
        handler = WatchedFileHandler(target, encoding='utf-8', delay=True)
        handler.setFormatter(EventFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False


def audit(event, *, channel='collection', **fields):
    if channel not in CHANNELS:
        raise ValueError('unknown audit channel')
    try:
        logging.getLogger('catalog.audit.' + channel).info('', extra={'audit_event': event, 'audit_fields': fields})
    except (OSError, ValueError) as error:
        logging.getLogger('catalog.logging').error('audit write failed: %s', type(error).__name__)
