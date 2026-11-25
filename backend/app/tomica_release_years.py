"""Fill missing release years from the exact catalogue identity; never infer batch codes."""
from collections import defaultdict
from datetime import date
import json
from pathlib import Path
import re
import time
from urllib.parse import unquote, urlsplit

from sqlalchemy import select

from .audit import audit
from .config import ROOT
from .models import FieldOverride, SourceIdentity, TomicaModel, TomicaVariant

FACTS = ROOT / 'backend/data/tomica-release-years.json'


def source_year(evidence):
    years = set()
    for field in ('caption', 'group', 'description', 'raw_header'):
        text = str(evidence.get(field, '')).strip()
        # A standalone catalogue date or an explicitly labelled release date.
        # Car model years, anniversary titles and manufacturing codes are not dates.
        matches = []
        if field == 'raw_header':
            matches = re.findall(r'(?<!\d)((?:19|20)\d{2})[./](?:0?[1-9]|1[0-2])\s*[～~]', text)
        else:
            match = re.fullmatch(r'((?:19|20)\d{2})[./年](?:0?[1-9]|1[0-2])(?:月|[./](?:[12]?\d|3[01]))?\s*(?:発売(?:予定)?)?', text)
            if match:
                matches.append(match[1])
            matches += re.findall(r'(?:発売(?:日|年月)?\s*[:：]?\s*)((?:19|20)\d{2})[./年](?:0?[1-9]|1[0-2])(?!\d)', text)
        years.update(int(year) for year in matches if 1970 <= int(year) <= date.today().year + 1)
    return next(iter(years)) if len(years) == 1 else None


def same_page(left, right):
    a, b = urlsplit(left), urlsplit(right)
    return a.hostname == b.hostname and unquote(a.path) == unquote(b.path)


def fill_missing_years(session, facts):
    models = {m.id: m for m in session.scalars(select(TomicaModel))}
    variants = {v.id: v for v in session.scalars(select(TomicaVariant))}
    overrides = {(o.kind, o.entity_key) for o in session.scalars(
        select(FieldOverride).where(FieldOverride.field == 'release_year'))}
    proposed = defaultdict(list)
    for identity in session.scalars(select(SourceIdentity).where(SourceIdentity.needs_review.is_(False))):
        evidence = identity.evidence
        if identity.source == 'tomica' and identity.kind == 'tomica_model':
            model = models.get(identity.entity_id)
            if (model is None or model.source_locator != identity.source_key
                    or not same_page(model.source_url, evidence.get('url', ''))):
                continue
            year = source_year(evidence)
            if year:
                proposed[('tomica_model', model.id)].append((year, {'source_url': evidence['url'],
                    'source_key': identity.source_key, 'catalogue_date': {k: evidence[k] for k in
                        ('caption', 'group', 'description', 'raw_header') if k in evidence}}))
        elif identity.kind == 'product':
            jan = identity.source_key
            fact = facts.get(jan)
            url = 'https://takaratomymall.jp/shop/g/g' + jan + '/'
            if (not fact or evidence.get('jan') != jan or evidence.get('source_url') != url
                    or fact.get('source_url') != url or not fact.get('text')):
                continue
            year = fact.get('year')
            labelled = re.search(r'発売日\s*:\s*\|\s*((?:19|20)\d{2})年', fact['text'])
            if not labelled or int(labelled[1]) != year:
                continue
            if not isinstance(year, int) or not 1970 <= year <= date.today().year + 1:
                continue
            model = models.get(identity.entity_id)
            variant = variants.get(evidence.get('variant_id'))
            if variant is not None and variant.model_id == identity.entity_id:
                target = ('tomica_variant', variant.id)
            elif (not evidence.get('variant_id') and model is not None
                    and model.source_locator == 'JAN:' + jan and model.source_url == url):
                target = ('tomica_model', model.id)
            else:
                # A current retail date cannot establish the first release of an
                # older base model, nor choose an unidentified historical variant.
                continue
            proposed[target].append((year, fact))
    changes, conflicts = [], []
    for (kind, key), candidates in proposed.items():
        row = (models if kind == 'tomica_model' else variants)[key]
        if row.release_year is not None or (kind, key) in overrides:
            continue
        years = {year for year, _ in candidates}
        if len(years) != 1:
            conflicts.append({'kind': kind, 'id': key, 'years': sorted(years)})
            continue
        year = years.pop()
        changes.append({'kind': kind, 'id': key, 'previous_year': None, 'year': year,
                        'evidence': [proof for _, proof in candidates]})
        row.release_year = year
    if changes:
        from .repository import CatalogRepository
        CatalogRepository(session).bump_revision('tomica')
    return {'changed_models': sum(c['kind'] == 'tomica_model' for c in changes),
            'changed_variants': sum(c['kind'] == 'tomica_variant' for c in changes),
            'remaining_unknown_models': sum(m.release_year is None for m in models.values()),
            'changes': changes, 'conflicts': conflicts}


def run(app, directory):
    facts = json.loads(FACTS.read_text(encoding='utf-8')) if FACTS.exists() else {}
    report = Path(directory) / 'release-years.json'
    with app.state.session_factory() as session:
        result = fill_missing_years(session, facts)
        # Save the prior null values and exact evidence before committing writes.
        if result['changes']:
            backup = Path(directory) / ('release-years-' + str(time.time_ns()) + '.json')
            backup.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
        session.commit()
    result['status'] = 'completed'
    result['facts'] = len(facts)
    report.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    audit('tomica_release_years_completed', changed_models=result['changed_models'],
          changed_variants=result['changed_variants'], conflicts=len(result['conflicts']))
