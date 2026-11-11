"""Authentication before private routes, static assets and shared catalog caches."""
import hmac
from pathlib import Path
import sqlite3
from urllib.parse import quote, urlsplit

import anyio
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .audit import audit, configure_audit
from .auth_store import AuthError, AuthStore
from .config import ROOT

COOKIE = 'catalog_session'
PUBLIC = {'/health/live', '/health/ready', '/login', '/login/', '/auth-assets/auth.css', '/auth-assets/auth.js', '/api/auth/login', '/api/auth/logout'}
ACCOUNT_PATHS = {'/account', '/account/', '/api/auth/me', '/api/auth/password'}
SERVICE_ROOTS = ('/api/tomica', '/api/pokemon', '/api/reference-images', '/api/tomica-news')
router = APIRouter(prefix='/api/auth')


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class PasswordBody(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=15, max_length=128)


def request_token(request):
    authorization = request.headers.get('authorization', '')
    if authorization:
        return authorization[7:] if authorization.startswith('Bearer ') else ''
    return request.cookies.get(COOKIE, '')


def csrf_check(request):
    if request.headers.get('x-catalog-client') not in {'web', 'miniprogram'}:
        raise AuthError('INVALID_CLIENT', '请通过登录页面操作', 403)
    if request.headers.get('sec-fetch-site') == 'cross-site':
        raise AuthError('INVALID_ORIGIN', '请求来源无效', 403)
    origin = request.headers.get('origin')
    target = urlsplit(str(request.url))
    if origin and origin != target.scheme + '://' + target.netloc:
        raise AuthError('INVALID_ORIGIN', '请求来源无效', 403)
    if not request.headers.get('content-type', '').lower().startswith('application/json'):
        raise AuthError('INVALID_CONTENT_TYPE', '请使用JSON提交', 415)


def auth_event(request, event, **fields):
    audit(event, channel='auth', client_ip=request.client.host if request.client else '',
          user_agent=request.headers.get('user-agent', '')[:200], **fields)


def auth_response(request, token, profile):
    payload = dict(profile)
    if request.headers.get('x-catalog-client') == 'miniprogram':
        payload['access_token'] = token
    response = JSONResponse(payload, headers={'Cache-Control': 'private, no-store'})
    settings = request.app.state.settings
    response.set_cookie(COOKIE, token, max_age=settings.auth_session_seconds, httponly=True,
                        secure=settings.auth_cookie_secure, samesite='lax', path='/')
    return response


@router.post('/login')
async def login(body: LoginBody, request: Request):
    csrf_check(request)
    store = request.app.state.auth_store
    if store is None:
        raise AuthError('AUTH_DISABLED', '登录服务未启用', 503)
    try:
        token, profile = await anyio.to_thread.run_sync(store.login, body.username, body.password, request.client.host if request.client else '')
    except AuthError as error:
        auth_event(request, 'login_rejected', username=body.username.strip().casefold(), code=error.code)
        raise
    auth_event(request, 'login_succeeded', username=profile['username'])
    return auth_response(request, token, profile)


@router.get('/me')
async def me(request: Request):
    if not request.app.state.settings.auth_enabled:
        return {'auth_enabled': False, 'username': None, 'must_change_password': False, 'expires_at': None}
    return request.state.identity


@router.post('/password')
async def change_password(body: PasswordBody, request: Request):
    csrf_check(request)
    store = request.app.state.auth_store
    if store is None:
        raise AuthError('AUTH_DISABLED', '登录服务未启用', 503)
    token, profile = await anyio.to_thread.run_sync(store.change_password, request_token(request), body.current_password, body.new_password)
    auth_event(request, 'password_changed', username=profile['username'])
    return auth_response(request, token, profile)


@router.post('/logout')
async def logout(request: Request):
    csrf_check(request)
    store = request.app.state.auth_store
    if store is not None:
        token = request_token(request)
        profile = await anyio.to_thread.run_sync(store.authenticate, token)
        await anyio.to_thread.run_sync(store.logout, token)
        if profile:
            auth_event(request, 'logout_succeeded', username=profile['username'])
    response = JSONResponse({'ok': True}, headers={'Cache-Control': 'private, no-store'})
    response.delete_cookie(COOKIE, path='/', httponly=True, secure=request.app.state.settings.auth_cookie_secure, samesite='lax')
    return response


def service_request(request, settings):
    expected = settings.auth_service_token.get_secret_value()
    incoming = request.headers.get('x-catalog-service', '')
    path = request.url.path
    return bool(expected and incoming and request.client and request.client.host in {'127.0.0.1', '::1'}
                and request.method in {'GET', 'HEAD'} and any(path == p or path.startswith(p + '/') for p in SERVICE_ROOTS)
                and hmac.compare_digest(expected.encode(), incoming.encode()))


def document_request(request):
    path = request.url.path
    return request.method in {'GET', 'HEAD'} and (path in {'/', '/preview', '/preview/', '/preview/index.html', '/account', '/account/'}
                                                or request.headers.get('sec-fetch-dest') == 'document')


def denial(request, *, must_change=False):
    if document_request(request):
        target = request.url.path + ('?' + request.url.query if request.url.query else '')
        response = RedirectResponse(('/account/' if must_change else '/login/') + '?next=' + quote(target, safe=''), status_code=303)
    else:
        response = JSONResponse({'code': 'PASSWORD_CHANGE_REQUIRED' if must_change else 'AUTH_REQUIRED',
                                 'message': '请先修改临时密码' if must_change else '登录已失效，请重新登录'}, status_code=403 if must_change else 401)
    response.headers['Cache-Control'] = 'private, no-store'
    return response


def install_auth(app, settings):
    app.state.auth_store = AuthStore(settings.auth_path, settings.auth_session_seconds) if settings.auth_enabled else None
    if settings.auth_enabled:
        directory = Path(settings.artifact_dir)
        directory = directory if directory.is_absolute() else ROOT / directory
        configure_audit(directory.parent / 'logs', channels={'auth'})
    app.include_router(router)
    app.mount('/auth-assets', StaticFiles(directory=ROOT / 'backend/auth', check_dir=False), name='auth-assets')

    @app.get('/login/', include_in_schema=False)
    @app.get('/account/', include_in_schema=False)
    def auth_page():
        return FileResponse(ROOT / 'backend/auth/index.html', headers={'Cache-Control': 'no-store'})

    @app.exception_handler(AuthError)
    async def auth_error(request, error):
        headers = {'Cache-Control': 'private, no-store'}
        if error.retry_after:
            headers['Retry-After'] = str(error.retry_after)
        return JSONResponse({'code': error.code, 'message': error.message}, status_code=error.status, headers=headers)

    @app.middleware('http')
    async def guard(request, call_next):
        if not settings.auth_enabled:
            return await call_next(request)
        path = request.url.path
        admin_api = path == '/api/admin' or path.startswith('/api/admin/')
        if path not in PUBLIC and not admin_api and not service_request(request, settings):
            try:
                profile = await anyio.to_thread.run_sync(app.state.auth_store.authenticate, request_token(request))
            except (sqlite3.Error, OSError):
                return JSONResponse({'code': 'AUTH_UNAVAILABLE', 'message': '登录服务暂不可用'}, status_code=503, headers={'Cache-Control': 'no-store'})
            if not profile:
                return denial(request)
            request.state.identity = profile
            if profile['must_change_password'] and path not in ACCOUNT_PATHS:
                return denial(request, must_change=True)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'private, no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response
