"""Authenticated, read-only coverage report for the installed official collector."""
import inspect as pyinspect
from pathlib import Path
import sys

from fastapi import APIRouter, Request
from sqlalchemy import MetaData, Table, func, inspect, select

router = APIRouter(prefix='/api/tomica-maintenance')


@router.get('')
def coverage(request: Request):
    engine = request.app.state.engine
    inspector = inspect(engine)
    tables = []
    with engine.connect() as connection:
        for name in inspector.get_table_names():
            if 'tomica' not in name:
                continue
            table = Table(name, MetaData(), autoload_with=connection)
            entry = {'name': name, 'columns': {c.name: str(c.type) for c in table.columns},
                     'count': connection.scalar(select(func.count()).select_from(table))}
            if any(word in name for word in ('official', 'product')):
                row = connection.execute(select(table).limit(1)).mappings().first()
                entry['sample'] = dict(row) if row else None
            tables.append(entry)
    modules = []
    names = {route.endpoint.__module__ for route in request.app.routes
             if hasattr(route, 'endpoint') and 'tomica/official-images' in getattr(route, 'path', '')}
    names.update(name for name in sys.modules if name.startswith('backend.app.') and any(word in name for word in ('tomica', 'takaratomy', 'official')) and name != __name__)
    for name in sorted(names):
        module = sys.modules[name]
        functions = {}
        for key, value in vars(module).items():
            if pyinspect.isfunction(value) and value.__module__ == name:
                functions[key] = str(pyinspect.signature(value))
        paths = {key: str(value) for key, value in vars(module).items() if isinstance(value, Path)}
        classes = {key: {method: str(pyinspect.signature(value)) for method, value in vars(cls).items() if pyinspect.isfunction(value)} for key, cls in vars(module).items() if pyinspect.isclass(cls) and cls.__module__ == name}
        contracts = {key: pyinspect.getsource(value) for key, value in vars(module).items() if key in {'parse_snapshot', 'publish', 'enrich_rows', 'parse_product'} and pyinspect.isfunction(value) and value.__module__ == name}
        modules.append({'name': name, 'functions': functions, 'classes': classes, 'paths': paths, 'contracts': contracts})
    from .config import ROOT
    import json
    files = []
    directory = ROOT / 'backend/data'
    for path in directory.glob('*.json'):
        if not any(word in path.name for word in ('tomica', 'official')):
            continue
        data = json.loads(path.read_text(encoding='utf-8-sig'))
        shape = {key: {'type': type(value).__name__, 'count': len(value) if isinstance(value, (dict, list)) else None, 'sample': next(iter(value.items()), None) if isinstance(value, dict) else value[:1] if isinstance(value, list) else value} for key, value in data.items()} if isinstance(data, dict) else {'count': len(data), 'sample': data[:1]}
        files.append({'path': str(path), 'shape': shape})
    return {'tables': tables, 'collectors': modules, 'data_files': files}
