from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
import logging
from sqlalchemy import case, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from backend.app.models import ImageAsset, SourcePage, SyncItem, SyncRun, now
from backend.app.audit import audit
from backend.app.repository import CatalogError, CatalogRepository
from backend.app.sources.http import SourceHttpClient
from backend.app.sources.tomica import TomicaAdapter
from backend.app.sources.pokemon import PokemonAdapter
from .identity import IdentityResolver
from .images import ImageService

LOG = logging.getLogger('catalog.sync')
SOURCE_LOCKS = {'tomica': 71001, 'pokemon': 71002}


class SourceLease:
    def __init__(self, connection, key):
        self.connection, self.key = connection, key

    def assert_alive(self):
        if self.connection.closed or self.connection.invalidated:
            raise RuntimeError('source lease connection lost')

    def close(self):
        try:
            if not self.connection.closed and not self.connection.invalidated:
                self.connection.execute(text('SELECT pg_advisory_unlock(:key)'), {'key': self.key})
                self.connection.commit()
        finally:
            self.connection.close()


class SourceLockProvider:
    def __init__(self, engine):
        self.engine = engine

    def acquire(self, source):
        connection = self.engine.connect()
        try:
            acquired = connection.scalar(text('SELECT pg_try_advisory_lock(:key)'), {'key': SOURCE_LOCKS[source]})
            connection.commit()
            if acquired:
                return SourceLease(connection, SOURCE_LOCKS[source])
        except Exception:
            connection.close()
            raise
        connection.close()
        return None


@dataclass
class RunResult:
    run_id: str
    status: str
    complete: bool
    counts: dict


class SyncService:
    def __init__(self, session, settings, *, session_factory=None, http_client=None, lock_provider=None, image_service=None, clock=now):
        self.session, self.settings = session, settings
        self.session_factory = session_factory or sessionmaker(bind=session.get_bind(), expire_on_commit=False)
        self.http_client = http_client
        self.lock_provider = lock_provider or SourceLockProvider(session.get_bind())
        self.image_service, self.clock = image_service, clock

    def enqueue_run(self, source, mode, limit=None, replay_of=None):
        if source not in SOURCE_LOCKS or mode not in {'incremental', 'full'} or (limit is not None and limit < 1):
            raise CatalogError('INVALID_TASK', '同步参数无效', 422)
        if self.session.scalar(select(SyncRun).where(SyncRun.source == source, SyncRun.status.in_(['queued', 'running']))):
            raise CatalogError('SOURCE_BUSY', '该来源已有同步任务', 409)
        try:
            with self.session.begin_nested():
                run = SyncRun(source=source, mode=mode, limit=limit, replay_of=str(replay_of) if replay_of else None)
                self.session.add(run)
                self.session.flush()
                return run.id
        except IntegrityError:
            raise CatalogError('SOURCE_BUSY', '该来源已有同步任务', 409)

    def retry_run(self, run_id):
        run = self.session.get(SyncRun, str(run_id))
        if run is None:
            raise CatalogError('NOT_FOUND', '任务不存在', 404)
        if run.status in {'queued', 'running', 'succeeded'}:
            raise CatalogError('INVALID_STATE', '该任务不可重试', 409)
        new_id = self.enqueue_run(run.source, run.mode, replay_of=run.id)
        for item in self.session.scalars(select(SyncItem).where(SyncItem.run_id == run.id, SyncItem.status.in_(['failed', 'isolated', 'pending', 'processing']))):
            self.session.add(SyncItem(run_id=new_id, url=item.url))
        self.session.flush()
        return new_id

    def claim_next_run(self):
        with self.session_factory() as session, session.begin():
            rows = session.scalars(select(SyncRun).where(SyncRun.status.in_(['queued', 'running'])).order_by(SyncRun.requested_at).with_for_update(skip_locked=True))
            for row in rows:
                lease = self.lock_provider.acquire(row.source)
                if lease is not None:
                    lease.close()
                    return row.id
            return None

    @contextmanager
    def _checkpoint(self, lease):
        lease.assert_alive()
        binding = getattr(lease, 'connection', None)
        with (Session(bind=binding, expire_on_commit=False) if binding is not None else self.session_factory()) as session:
            with session.begin():
                if binding is not None:
                    session.execute(text('SELECT 1'))
                yield session

    def run_once(self, run_id):
        with self.session_factory() as session:
            run = session.get(SyncRun, str(run_id))
            if run is None:
                raise CatalogError('NOT_FOUND', '任务不存在', 404)
            source, mode, budget, replay = run.source, run.mode, run.limit, run.replay_of
        lease = self.lock_provider.acquire(source)
        if lease is None:
            return RunResult(str(run_id), 'busy', False, {})
        adapter = TomicaAdapter() if source == 'tomica' else PokemonAdapter()
        client = self.http_client or SourceHttpClient(source, interval=self.settings.source_interval_seconds)
        counts = {'pages': 0, 'changed': 0, 'created': 0, 'updated': 0, 'failed': 0, 'isolated': 0, 'unchanged': 0}
        try:
            with self._checkpoint(lease) as session:
                run = session.get(SyncRun, str(run_id))
                if run.status not in {'queued', 'running'}:
                    return RunResult(run.id, run.status, run.status == 'succeeded', run.stats)
                run.status, run.started_at = 'running', run.started_at or self.clock()
                existing = list(session.scalars(select(SyncItem).where(SyncItem.run_id == run.id)))
                for item in existing:
                    if item.status == 'processing':
                        item.status = 'pending'
                if not existing:
                    urls = list(adapter.seed_urls())
                    urls += list(session.scalars(select(SourcePage.url).where(SourcePage.source == source)))
                    for url in dict.fromkeys(urls):
                        session.add(SyncItem(run_id=run.id, url=url))
            audit('run_started', run_id=str(run_id), source=source, mode=mode, limit=budget)
            while budget is None or counts['pages'] < budget:
                with self._checkpoint(lease) as session:
                    priority = case((SyncItem.url.like('%/number/%'), 0), else_=1)
                    item = session.scalar(select(SyncItem).where(SyncItem.run_id == str(run_id), SyncItem.status == 'pending').order_by(priority, SyncItem.checked_at, SyncItem.id))
                    if item is None:
                        break
                    item.status, item.attempts = 'processing', item.attempts + 1
                    item_id, url = item.id, item.url
                    old = session.scalar(select(SourcePage).where(SourcePage.source == source, SourcePage.url == url))
                    etag, modified, digest = (old.etag, old.last_modified, old.content_hash) if old else (None, None, None)
                fetched = client.fetch(url, etag if mode == 'incremental' else None, modified if mode == 'incremental' else None, digest if mode == 'incremental' else None)
                counts['pages'] += 1
                changes, image_links = [], 0
                try:
                    if fetched.error:
                        raise ValueError(fetched.error)
                    parsed = None if fetched.not_modified else adapter.parse(url, fetched.body)
                    if parsed:
                        self.validate_page(parsed)
                    with self._checkpoint(lease) as session:
                        item = session.get(SyncItem, item_id)
                        page = session.scalar(select(SourcePage).where(SourcePage.source == source, SourcePage.url == url))
                        if page is None:
                            page = SourcePage(source=source, url=url)
                            session.add(page)
                            session.flush()
                        repo = CatalogRepository(session)
                        if parsed:
                            if page.accepted_count and len(parsed.candidates) < page.accepted_count * 0.8:
                                raise CatalogError('COUNT_DROP', '页面条目数量异常下降')
                            if page.discovered_urls and parsed.discovered_urls and len(parsed.discovered_urls) < len(page.discovered_urls) * 0.8 and url in adapter.seed_urls():
                                raise CatalogError('DISCOVERY_DROP', '来源清单异常下降')
                            repo.stage_page(run_id, parsed)
                            for candidate in parsed.candidates:
                                if IdentityResolver().resolve(candidate, repo).entity_key is None:
                                    raise CatalogError('IDENTITY_AMBIGUOUS', '证据对应多个条目，等待核对')
                            self.attach_images(parsed, session)
                            changed = repo.publish_candidates(run_id, parsed.candidates, source=source, changes=changes)
                            image_links = self.link_model_images(session, parsed)
                            changed += image_links
                            counts['changed'] += changed
                            if changed:
                                repo.bump_revision(source)
                            page.etag, page.last_modified, page.content_hash = fetched.etag, fetched.last_modified, fetched.content_hash
                            page.discovered_urls, page.accepted_count = parsed.discovered_urls, len(parsed.candidates)
                        else:
                            counts['unchanged'] += 1
                        page.checked_at, page.last_success_at = self.clock(), self.clock()
                        unresolved = parsed is not None and any(issue.code == 'IDENTITY_AMBIGUOUS' for issue in parsed.issues)
                        item.status, item.checked_at = ('isolated' if unresolved else 'succeeded'), self.clock()
                        if not replay:
                            known = set(session.scalars(select(SyncItem.url).where(SyncItem.run_id == str(run_id))))
                            for target in page.discovered_urls:
                                if target not in known:
                                    session.add(SyncItem(run_id=str(run_id), url=target))
                                    known.add(target)
                        created = sum(c['action'] == 'created' for c in changes)
                        updated = len(changes) - created
                        session.get(SyncRun, str(run_id)).stats = {**counts, 'created': counts['created'] + created, 'updated': counts['updated'] + updated}
                        page_status = item.status
                    counts['created'] += created
                    counts['updated'] += updated
                    for change in changes:
                        audit('record_' + change['action'], run_id=str(run_id), source=source, url=url, **change)
                    audit('page_checked', run_id=str(run_id), source=source, url=url, http_status=fetched.status, status=page_status, not_modified=fetched.not_modified, created=created, updated=updated, image_links=image_links, candidates=len(parsed.candidates) if parsed else 0)
                    LOG.info('source=%s pages=%s changed=%s url=%s', source, counts['pages'], counts['changed'], url)
                except (ValueError, CatalogError) as error:
                    with self._checkpoint(lease) as session:
                        item = session.get(SyncItem, item_id)
                        item.status = 'isolated' if isinstance(error, CatalogError) else 'failed'
                        item.issues = [{'code': getattr(error, 'code', 'FETCH_OR_PARSE_FAILED'), 'message': str(error)[:300], 'url': url}]
                        if fetched.retry_after > 300:
                            item.next_retry_at = self.clock() + timedelta(seconds=fetched.retry_after)
                        counts['isolated' if item.status == 'isolated' else 'failed'] += 1
                    audit('page_failed', run_id=str(run_id), source=source, url=url, http_status=fetched.status, code=getattr(error, 'code', 'FETCH_OR_PARSE_FAILED'), message=str(error)[:300])
            with self._checkpoint(lease) as session:
                run = session.get(SyncRun, str(run_id))
                pending = session.scalar(select(SyncItem.id).where(SyncItem.run_id == run.id, SyncItem.status == 'pending')) is not None
                counts['failed'] = len(list(session.scalars(select(SyncItem.id).where(SyncItem.run_id == run.id, SyncItem.status == 'failed'))))
                counts['isolated'] = len(list(session.scalars(select(SyncItem.id).where(SyncItem.run_id == run.id, SyncItem.status == 'isolated'))))
                status = 'partial' if counts['failed'] or counts['isolated'] else 'limited' if pending else 'succeeded'
                run.status, run.finished_at, run.stats = status, self.clock(), counts
                if run.followup_mode == 'full':
                    session.flush()
                    session.add(SyncRun(source=source, mode='full'))
                result = RunResult(run.id, status, status == 'succeeded' and not budget, counts)
            audit('run_finished', run_id=str(run_id), source=source, mode=mode, status=result.status, complete=result.complete, counts=counts)
            return result
        except Exception as error:
            with self.session_factory() as session, session.begin():
                run = session.get(SyncRun, str(run_id))
                run.status, run.last_error = 'failed', type(error).__name__
            audit('run_failed', run_id=str(run_id), source=source, error_type=type(error).__name__, counts=counts)
            raise
        finally:
            if self.http_client is None:
                client.close()
            lease.close()

    def validate_page(self, page):
        seen = {}
        for candidate in page.candidates:
            resolved = IdentityResolver().resolve(candidate, None)
            if resolved.entity_key is None:
                raise CatalogError('IDENTITY_AMBIGUOUS', '条目身份待核对')
            key = (candidate.kind, candidate.source_key)
            if key in seen and seen[key] != candidate.fields:
                raise CatalogError('IDENTITY_AMBIGUOUS', '同一身份存在冲突内容')
            seen[key] = candidate.fields
            if candidate.kind == 'pokemon' and (not candidate.fields.get('name_zh') or candidate.fields.get('dex', 0) < 1):
                raise CatalogError('INVALID_POKEMON', '全国编号或名称缺失')
            if candidate.kind == 'tomica_model' and not candidate.fields.get('name_original'):
                raise CatalogError('INVALID_TOMICA', '车型名称缺失')

    def attach_images(self, page, session):
        for candidate in page.candidates:
            if candidate.kind == 'pokemon_detail':
                for pair in candidate.fields['data'].get('shiny_pairs', []):
                    for mode in ['normal', 'shiny']:
                        url = pair[mode + '_source_url']
                        image = session.scalar(select(ImageAsset).where(ImageAsset.source_url == url))
                        if image is None:
                            image = ImageAsset(source_url=url)
                            session.add(image)
                            session.flush()
                        pair[mode + '_image_id'] = image.id
            url = candidate.evidence.get('image_url')
            if not url or candidate.kind not in {'tomica_variant', 'pokemon', 'pokemon_form'}:
                continue
            image = session.scalar(select(ImageAsset).where(ImageAsset.source_url == url))
            if image is None:
                image = ImageAsset(source_url=url)
                session.add(image)
                session.flush()
            candidate.fields['primary_image_id' if candidate.kind == 'pokemon' else 'image_id'] = image.id

    def link_model_images(self, session, page):
        from backend.app.models import SourceIdentity, TomicaModel
        changed = 0
        for candidate in page.candidates:
            if candidate.kind != 'tomica_model':
                continue
            identity = session.scalar(select(SourceIdentity).where(SourceIdentity.source == 'tomica', SourceIdentity.kind == 'tomica_model', SourceIdentity.source_key == candidate.source_key))
            model = session.get(TomicaModel, identity.entity_id)
            first = next((v for v in page.candidates if v.kind == 'tomica_variant' and v.evidence.get('model_key') == candidate.source_key and v.fields.get('image_id')), None)
            if first and model.primary_image_id != first.fields['image_id']:
                model.primary_image_id = first.fields['image_id']
                changed += 1
        return changed
