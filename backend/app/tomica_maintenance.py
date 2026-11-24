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
    for name in names:
        module = sys.modules[name]
        functions = {}
        for key, value in vars(module).items():
            if pyinspect.isfunction(value) and value.__module__ == name:
                functions[key] = str(pyinspect.signature(value))
        paths = {key: str(value) for key, value in vars(module).items() if isinstance(value, Path)}
        modules.append({'name': name, 'functions': functions, 'paths': paths})
    return {'tables': tables, 'collectors': modules}
