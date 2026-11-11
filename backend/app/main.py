from contextlib import asynccontextmanager
import logging
import anyio
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from .config import ROOT, Settings
from .repository import CatalogError
from .api import get_session


def create_app(settings):
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    @asynccontextmanager
    async def lifespan(app):
        yield
        app.state.cache.close()
        engine.dispose()
    app = FastAPI(title='双图鉴 API', version='0.1.0', lifespan=lifespan)
    app.state.settings = settings
    app.state.session_factory = sessionmaker(engine, expire_on_commit=False)
    app.state.engine = engine
    from .cache import CatalogCache
    app.state.cache = CatalogCache(settings.redis_url.get_secret_value(), settings.cache_namespace)
    app.state.image_limiter = anyio.CapacityLimiter(3)
    from .api import router as api_router
    from .admin import router as admin_router
    from .news import router as news_router
    from .gunpla import router as gunpla_router
    app.include_router(api_router)
    app.include_router(news_router)
    app.include_router(gunpla_router)
    app.include_router(admin_router)

    @app.exception_handler(CatalogError)
    async def domain_error(request, error):
        return JSONResponse({'code': error.code, 'message': error.message}, status_code=error.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        return JSONResponse({'code': 'INVALID_PARAMETERS', 'message': '请检查查询参数或提交内容'}, status_code=422)

    @app.exception_handler(Exception)
    async def unexpected_error(request, error):
        logging.getLogger('catalog.api').error('request failed: %s', type(error).__name__)
        return JSONResponse({'code': 'INTERNAL_ERROR', 'message': '服务暂时不可用，请稍后重试'}, status_code=500)

    @app.get('/health/live')
    def live():
        return {'status': 'ok'}

    @app.get('/health/ready')
    def ready():
        try:
            with engine.connect() as connection:
                connection.execute(text('SELECT 1'))
                revision = connection.scalar(text('SELECT version_num FROM alembic_version'))
            head = ScriptDirectory.from_config(Config(str(ROOT / 'backend/alembic.ini'))).get_current_head()
            if revision != head:
                raise ValueError('migration mismatch')
            return {'status': 'ready', 'revision': revision}
        except Exception:
            return JSONResponse({'status': 'not_ready'}, status_code=503)

    @app.get('/')
    def home():
        return RedirectResponse('/preview/')

    app.mount('/admin', StaticFiles(directory=ROOT / 'backend/admin', html=True, check_dir=False), name='admin')
    app.mount('/preview', StaticFiles(directory=ROOT / 'backend/preview', html=True, check_dir=False), name='preview')
    from .auth import install_auth
    install_auth(app, settings)
    return app


app = create_app(Settings())
