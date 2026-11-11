import base64
import json
import secrets
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from .api import get_session
from .models import SyncItem, SyncRun
from .repository import CatalogError, CatalogRepository
from .schemas import OverrideRequest, SyncRequest
from .sync.service import SyncService

router = APIRouter(prefix='/api/admin')


def require_admin(request: Request):
    expected = request.app.state.settings.admin_token.get_secret_value()
    if not expected:
        raise CatalogError('ADMIN_DISABLED', '管理功能尚未启用', 503)
    authorization = request.headers.get('authorization', '')
    token = authorization[7:] if authorization.startswith('Bearer ') else ''
    if not token or not secrets.compare_digest(token.encode(), expected.encode()):
        raise CatalogError('UNAUTHORIZED', '请提供有效管理凭证', 401)
    return 'admin'


def get_sync_service(request: Request, session: Session = Depends(get_session)):
    return SyncService(session=session, settings=request.app.state.settings, session_factory=request.app.state.session_factory)


def admin_page(rows, cursor, limit, key):
    values = [{c.name: getattr(row, c.name) for c in row.__table__.columns} for row in rows]
    values.sort(key=lambda v: (str(v[key]), v['id']), reverse=True)
    if cursor:
        try:
            last = tuple(json.loads(base64.urlsafe_b64decode(cursor)))
            values = [v for v in values if (str(v[key]), v['id']) < last]
        except (ValueError, TypeError):
            raise CatalogError('INVALID_CURSOR', '管理分页参数无效')
    selected = values[:limit]
    token = base64.urlsafe_b64encode(json.dumps([str(selected[-1][key]), selected[-1]['id']]).encode()).decode() if len(values) > limit else None
    return {'items': selected, 'next_cursor': token}


@router.get('/runs', dependencies=[Depends(require_admin)])
def list_runs(source: str | None = None, status: str | None = None, cursor: str | None = None, limit: int = Query(30, ge=1, le=100), session: Session = Depends(get_session)):
    query = select(SyncRun)
    if source:
        query = query.where(SyncRun.source == source)
    if status:
        query = query.where(SyncRun.status == status)
    return admin_page(session.scalars(query), cursor, limit, 'requested_at')


@router.get('/issues', dependencies=[Depends(require_admin)])
def list_issues(source: str | None = None, run_id: str | None = None, status: str | None = None, cursor: str | None = None, limit: int = Query(30, ge=1, le=100), session: Session = Depends(get_session)):
    query = select(SyncItem).join(SyncRun).where(SyncItem.status.in_(['failed', 'isolated', 'pending']))
    if source:
        query = query.where(SyncRun.source == source)
    if run_id:
        query = query.where(SyncItem.run_id == run_id)
    if status:
        query = query.where(SyncItem.status == status)
    return admin_page(session.scalars(query), cursor, limit, 'run_id')


@router.post('/sync', status_code=202, dependencies=[Depends(require_admin)])
def enqueue_sync(body: SyncRequest, session: Session = Depends(get_session), service: SyncService = Depends(get_sync_service)):
    with session.begin():
        run_id = service.enqueue_run(body.source, body.mode)
    return {'run_id': str(run_id)}


@router.post('/runs/{run_id}/retry', status_code=202, dependencies=[Depends(require_admin)])
def retry_sync(run_id: str, session: Session = Depends(get_session), service: SyncService = Depends(get_sync_service)):
    with session.begin():
        new_id = service.retry_run(run_id)
    return {'run_id': str(new_id)}


@router.patch('/overrides')
def set_override(body: OverrideRequest, session: Session = Depends(get_session), actor: str = Depends(require_admin)):
    with session.begin():
        value = CatalogRepository(session).set_override(body.kind, body.entity_key, body.field, body.value, actor)
    return value
