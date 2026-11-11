"""Query private project logs without exposing a public log endpoint."""
import argparse
from collections import Counter, deque
from datetime import datetime, timedelta, timezone
import gzip
import json
from pathlib import Path
import re


def parse_time(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    return result if result.tzinfo else result.replace(tzinfo=timezone(timedelta(hours=8)))


def records(directory, kind):
    def order(path):
        match = re.search(r'\.jsonl\.(\d+)', path.name)
        return int(match[1]) if match else 0
    for path in sorted(Path(directory).glob(kind + '.jsonl*'), key=order, reverse=True):
        if not path.is_file():
            continue
        opener = gzip.open if path.suffix == '.gz' else open
        with opener(path, 'rt', encoding='utf-8') as stream:
            for line in stream:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind', choices=['access', 'collection', 'deploy'])
    parser.add_argument('--directory', type=Path, default=Path('/opt/dual-catalog/data/artifacts/logs'))
    parser.add_argument('--since', type=parse_time, help='ISO时间；省略时区按北京时间')
    parser.add_argument('--ip')
    parser.add_argument('--event')
    parser.add_argument('--summary', action='store_true', help='按IP汇总请求次数，含图片和接口请求')
    parser.add_argument('--limit', type=int, default=50)
    args = parser.parse_args()
    if not 1 <= args.limit <= 1000:
        parser.error('limit must be between 1 and 1000')
    if (args.ip or args.summary) and args.kind != 'access':
        parser.error('--ip and --summary only apply to access logs')
    recent, counts, spans, failures = deque(maxlen=args.limit), Counter(), {}, Counter()
    for row in records(args.directory, args.kind):
        if args.since and parse_time(row['time']) < args.since:
            continue
        if args.ip and row.get('client_ip') != args.ip or args.event and row.get('event') != args.event:
            continue
        if args.summary:
            ip = row['client_ip']
            counts[ip] += 1
            if ip not in spans:
                spans[ip] = [row['time'], row['time']]
            spans[ip][1] = row['time']
            failures[ip] += int(row['status'] >= 400)
        else:
            recent.append(row)
    result = [{'client_ip': ip, 'requests': count, 'first': spans[ip][0], 'last': spans[ip][1], 'errors': failures[ip]} for ip, count in counts.most_common(args.limit)] if args.summary else recent
    for row in result:
        print(json.dumps(row, ensure_ascii=False))


if __name__ == '__main__':
    main()
