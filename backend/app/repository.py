import base64
import hashlib
import json
from urllib.parse import urlsplit, urlunsplit, quote, unquote
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, load_only

from .models import CatalogRevision, Evolution, FieldOverride, ImageAsset, Pokemon, PokemonDetail, PokemonForm, SourceIdentity, SyncItem, TomicaModel, TomicaVariant, now
from .schemas import ParsedPage, PokemonQuery, SourceCandidate, TomicaQuery

ENTITIES = {'tomica_model': TomicaModel, 'tomica_variant': TomicaVariant, 'pokemon': Pokemon, 'pokemon_form': PokemonForm, 'pokemon_detail': PokemonDetail, 'evolution': Evolution}
OVERRIDES = {'tomica_model': {'name_display', 'brand', 'release_year', 'release_month', 'scale'}, 'tomica_variant': {'description', 'country', 'release_year', 'release_month'}, 'pokemon': {'name_zh', 'name_ja', 'name_en', 'types', 'height_m', 'weight_kg', 'abilities'}, 'pokemon_form': {'display_name', 'types'}}


class CatalogError(Exception):
    def __init__(self, code, message, status=400):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


class CatalogRepository:
    def __init__(self, session: Session, cache=None):
        self.session = session
        self.cache = cache

    def catalog_rows(self, source):
        model, kind = (TomicaModel, 'tomica_model') if source == 'tomica' else (Pokemon, 'pokemon')
        def load():
            overrides = {}
            for override in self.session.scalars(select(FieldOverride).where(FieldOverride.kind == kind)):
                overrides.setdefault(override.entity_key, []).append(override)
            rows = []
            for row in self.session.scalars(select(model)):
                key = str(row.dex) if kind == 'pokemon' else str(row.id)
                rows.append(self._project_row(row, overrides.get(key, [])))
            image_ids = {row.get('primary_image_id') or row.get('image_id') for row in rows} - {None}
            assets = {asset.id: asset for asset in self.session.scalars(select(ImageAsset).options(load_only(ImageAsset.id, ImageAsset.source_url, ImageAsset.public_url, ImageAsset.status, ImageAsset.attribution)).where(ImageAsset.id.in_(image_ids)))} if image_ids else {}
            for row in rows:
                row.update(self._image_metadata(assets.get(row.get('primary_image_id') or row.get('image_id'))))
            return rows
        if self.cache is None:
            return load()
        return self.cache.snapshot(source, self.get_revision(source), load, ttl=600)

    def get_revision(self, source):
        row = self.session.get(CatalogRevision, source)
        return row.revision if row else 0

    def bump_revision(self, source):
        row = self.session.get(CatalogRevision, source)
        if row is None:
            row = CatalogRevision(source=source, revision=0)
            self.session.add(row)
        row.revision += 1

    def image(self, image_id):
        row = self.session.get(ImageAsset, image_id) if image_id else None
        return self._image_metadata(row)

    @staticmethod
    def _image_metadata(row):
        reference = None
        if row:
            parts = urlsplit(row.source_url)
            allowed = parts.hostname in {'tomica.minibird.jp', 's1.52poke.com'} or (parts.hostname == 'staticcdn.bandaihobbysite.cn' and parts.scheme == 'https')
            if parts.scheme in {'http', 'https'} and allowed and not parts.username and not parts.password and not parts.port and not parts.query:
                try:
                    if parts.hostname == 'tomica.minibird.jp':
                        from .sources.http import normalize_url
                        reference = normalize_url(row.source_url, row.source_url, 'tomica')
                    else:
                        reference = urlunsplit((parts.scheme, parts.netloc, quote(unquote(parts.path), safe='/()_-.,&:!'), '', ''))
                except (ValueError, UnicodeError):
                    reference = None
        return {'image_url': row.public_url if row and row.status == 'ready' else None, 'preview_image_url': '/api/reference-images/' + str(row.id) if row and reference else None, 'source_image_url': reference, 'image_status': row.status if row else 'missing', 'image_attribution': (row.attribution or ('Tomica Collection' if 'tomica' in row.source_url else '神奇宝贝百科')) if row else None}

    @staticmethod
    def _project_row(row, overrides):
        result = {c.name: getattr(row, c.name) for c in row.__table__.columns}
        for override in overrides:
            result[override.field] = override.value
        return result

    def effective(self, row, kind):
        key = str(row.dex) if kind == 'pokemon' else str(row.id)
        overrides = self.session.scalars(select(FieldOverride).where(FieldOverride.kind == kind, FieldOverride.entity_key == key))
        result = self._project_row(row, overrides)
        result.update(self.image(result.get('primary_image_id') or result.get('image_id')))
        return result

    def get_tomica(self, model_id):
        row = self.session.get(TomicaModel, str(model_id))
        if row is None:
            return None
        result = self.effective(row, 'tomica_model')
        result['variants'] = [self.effective(v, 'tomica_variant') for v in self.session.scalars(select(TomicaVariant).where(TomicaVariant.model_id == row.id).order_by(TomicaVariant.id))]
        return result

    def get_pokemon(self, dex):
        row = self.session.scalar(select(Pokemon).where(Pokemon.dex == dex))
        if row is None:
            return None
        result = self.effective(row, 'pokemon')
        extra = self.session.scalar(select(PokemonDetail).where(PokemonDetail.dex == dex))
        result['extra'] = dict(extra.data) if extra else {}
        result['extra']['shiny_pairs'] = [{**pair, 'normal': self.image(pair.get('normal_image_id')), 'shiny': self.image(pair.get('shiny_image_id'))} for pair in result['extra'].get('shiny_pairs', [])]
        result['details_updated_at'] = extra.updated_at if extra else None
        result['forms'] = [self.effective(f, 'pokemon_form') for f in self.session.scalars(select(PokemonForm).where(PokemonForm.dex == dex).order_by(PokemonForm.form_key))]
        result['forms'].sort(key=lambda form: (form['form_key'] != 'default', form['form_key']))
        relations = self.session.scalars(select(Evolution).where((Evolution.from_dex == dex) | (Evolution.to_dex == dex)))
        result['evolutions'] = []
        for evolution in relations:
            value = self.effective(evolution, 'evolution')
            for side in ['from', 'to']:
                target = self.session.scalar(select(Pokemon).where(Pokemon.dex == value[side + '_dex']))
                value[side + '_name'] = target.name_zh if target else None
                value[side + '_available'] = target is not None
            result['evolutions'].append(value)
        return result

    def _page(self, rows, query, source, sort):
        filters = query.model_dump(exclude={'cursor', 'limit', 'page'})
        if source == 'pokemon':
            if not filters.get('region'):
                filters.pop('region', None)  # Preserve pre-region cursor signatures.
            else:
                from .pokemon_regions import region_index_version
                filters['region_index_version'] = region_index_version()
        signature = hashlib.sha256(json.dumps(filters, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        revision = self.get_revision(source)
        rows = sorted(rows, key=sort)
        if getattr(query, 'page', None) is not None:
            total = len(rows)
            pages = max(1, (total + query.limit - 1) // query.limit)
            page = min(query.page, pages)
            start = (page - 1) * query.limit
            return {'items': rows[start:start + query.limit], 'next_cursor': None, 'total': total, 'page': page, 'page_size': query.limit, 'total_pages': pages}
        if query.cursor:
            try:
                cursor = json.loads(base64.urlsafe_b64decode(query.cursor))
                if cursor['filter_hash'] != signature:
                    raise ValueError('filter mismatch')
                if cursor['revision'] != revision:
                    raise CatalogError('CATALOG_CHANGED', '图鉴已更新，请重新加载', 409)
                rows = [r for r in rows if tuple(sort(r)) > tuple(cursor['sort_key'])]
            except CatalogError:
                raise
            except (ValueError, KeyError, TypeError):
                raise CatalogError('INVALID_CURSOR', '分页参数无效')
        items = rows[:query.limit]
        next_cursor = None
        if len(rows) > query.limit:
            value = {'sort_key': sort(items[-1]), 'filter_hash': signature, 'revision': revision}
            next_cursor = base64.urlsafe_b64encode(json.dumps(value).encode()).decode()
        return {'items': items, 'next_cursor': next_cursor}

    def list_tomica(self, query: TomicaQuery):
        from .car_search import matches_car
        rows = self.catalog_rows('tomica')
        if query.brand:
            rows = [r for r in rows if (r['brand'] is None if query.brand == 'unknown' else r['brand'] == query.brand)]
        if query.year is not None:
            rows = [r for r in rows if (r['release_year'] is None if query.year == 'unknown' else r['release_year'] == query.year)]
        if query.q:
            rows = [r for r in rows if matches_car(r, query.q)]
        return self._page(rows, query, 'tomica', lambda r: (r['release_year'] or 99999, r['id']))

    def list_pokemon(self, query: PokemonQuery):
        rows = self.catalog_rows('pokemon')
        if query.region:
            from .pokemon_regions import region_dexes
            members = region_dexes(query.region)
            rows = [r for r in rows if r['dex'] in members]
        if query.type:
            rows = [r for r in rows if query.type in r['types']]
        if query.q:
            q = query.q.lstrip('#').casefold()
            rows = [r for r in rows if (q.isdigit() and int(q) == r['dex']) or any(q in str(r[k] or '').casefold() for k in ['name_zh', 'name_ja', 'name_en'])]
        return {**self._page(rows, query, 'pokemon', lambda r: (r['dex'],)), 'total': len(rows)}

    def get_tomica_filters(self):
        rows = self.catalog_rows('tomica')
        return {'brands': sorted({r['brand'] for r in rows if r['brand']}), 'years': sorted({r['release_year'] for r in rows if r['release_year']}, reverse=True), 'unknown_brand': any(not r['brand'] for r in rows), 'unknown_year': any(not r['release_year'] for r in rows)}

    def stage_page(self, run_id, page: ParsedPage):
        row = self.session.scalar(select(SyncItem).where(SyncItem.run_id == str(run_id), SyncItem.url == page.url))
        if row is None:
            row = SyncItem(run_id=str(run_id), url=page.url)
            self.session.add(row)
        row.candidates = [c.model_dump() for c in page.candidates]
        row.issues = [i.model_dump() for i in page.issues]
        return row

    def publish_candidates(self, run_id, candidates: list[SourceCandidate], source=None, changes=None):
        changed = 0
        for candidate in candidates:
            if not candidate.source_key:
                raise CatalogError('IDENTITY_UNRESOLVED', '条目身份待核对')
            origin = source or ('tomica' if candidate.kind.startswith('tomica') else 'pokemon')
            identity = self.session.scalar(select(SourceIdentity).where(SourceIdentity.source == origin, SourceIdentity.kind == candidate.kind, SourceIdentity.source_key == candidate.source_key))
            # Collection pages repeat the same photograph under several indexes.
            # Retain the first verified caption and provenance for that edition;
            # its own page can still update it, and base model identities are separate.
            if identity and candidate.source_key.startswith('edition:') and identity.evidence.get('url') != candidate.evidence.get('url'):
                continue
            model = ENTITIES[candidate.kind]
            fields = {k: v for k, v in candidate.fields.items() if k in model.__table__.columns and k not in {'id', 'checked_at', 'updated_at'}}
            if candidate.kind == 'tomica_variant' and not fields.get('model_id'):
                parent = self.session.scalar(select(SourceIdentity).where(SourceIdentity.source == origin, SourceIdentity.kind == 'tomica_model', SourceIdentity.source_key == candidate.evidence.get('model_key')))
                if parent is None:
                    raise CatalogError('PARENT_MISSING', '车型关联缺失')
                fields['model_id'] = parent.entity_id
            row = self.session.get(model, identity.entity_id) if identity else None
            if row is None and candidate.kind == 'pokemon':
                row = self.session.scalar(select(Pokemon).where(Pokemon.dex == fields['dex']))
            created = row is None
            changed_fields = sorted(k for k, v in fields.items() if created or getattr(row, k) != v)
            is_changed = created or bool(changed_fields)
            if row is None:
                row = model(**fields)
                self.session.add(row)
                self.session.flush()
            else:
                for key, value in fields.items():
                    setattr(row, key, value)
            row.checked_at = now()
            if is_changed:
                row.updated_at = now()
                changed += 1
            if identity is None:
                self.session.add(SourceIdentity(source=origin, kind=candidate.kind, source_key=candidate.source_key, entity_id=row.id, evidence=candidate.evidence))
            elif candidate.source_key.startswith('edition:'):
                identity.evidence = candidate.evidence
            self.session.flush()
            if is_changed and changes is not None:
                name = next((getattr(row, key, None) for key in ['name_zh', 'name_original', 'display_name', 'variant_code'] if getattr(row, key, None)), candidate.source_key)
                changes.append({'action': 'created' if created else 'updated', 'kind': candidate.kind, 'entity_id': row.id, 'source_key': candidate.source_key, 'name': str(name)[:300], 'fields': changed_fields})
        return changed

    def set_override(self, kind, entity_key, field, value, actor='admin'):
        if field not in OVERRIDES.get(kind, set()):
            raise CatalogError('FIELD_FORBIDDEN', '该字段不可修改', 422)
        model = ENTITIES[kind]
        try:
            row = self.session.scalar(select(Pokemon).where(Pokemon.dex == int(entity_key))) if kind == 'pokemon' else self.session.get(model, entity_key)
        except ValueError:
            raise CatalogError('INVALID_VALUE', '条目标识无效', 422)
        if row is None:
            raise CatalogError('NOT_FOUND', '条目不存在', 404)
        if field in {'release_year', 'release_month', 'height_m', 'weight_kg'} and value is not None:
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0 or (field == 'release_month' and not 1 <= value <= 12):
                raise CatalogError('INVALID_VALUE', '数值无效', 422)
            if field in {'release_year', 'release_month'} and (not isinstance(value, int) or value < 1):
                raise CatalogError('INVALID_VALUE', '年月必须为正整数', 422)
        if field in {'types', 'abilities'} and (not isinstance(value, list) or not all(isinstance(v, str) for v in value)):
            raise CatalogError('INVALID_VALUE', '应提供文本数组', 422)
        if field == 'types':
            from .schemas import TYPES
            if any(t not in TYPES for t in value):
                raise CatalogError('INVALID_VALUE', '属性无效', 422)
        if field not in {'release_year', 'release_month', 'height_m', 'weight_kg', 'types', 'abilities'} and value is not None and not isinstance(value, str):
            raise CatalogError('INVALID_VALUE', '应提供文本', 422)
        existing = self.session.scalar(select(FieldOverride).where(FieldOverride.kind == kind, FieldOverride.entity_key == entity_key, FieldOverride.field == field))
        before = existing.value if existing else getattr(row, field)
        if existing is None:
            existing = FieldOverride(kind=kind, entity_key=entity_key, field=field, value=value, actor=actor)
            self.session.add(existing)
        else:
            existing.value, existing.actor, existing.updated_at = value, actor, now()
        if before != value:
            self.bump_revision('tomica' if kind.startswith('tomica') else 'pokemon')
        self.session.flush()
        return {'kind': kind, 'entity_key': entity_key, 'field': field, 'source_value': getattr(row, field), 'override_value': value, 'effective_value': value, 'actor': actor, 'updated_at': existing.updated_at}
