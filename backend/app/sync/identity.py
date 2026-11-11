from dataclasses import dataclass, field
import hashlib
import json
from backend.app.schemas import ParseIssue


@dataclass
class ResolvedIdentity:
    entity_key: str | None
    issues: list[ParseIssue] = field(default_factory=list)


class IdentityResolver:
    def resolve(self, candidate, repository):
        if candidate.source_key:
            if repository is not None and candidate.kind == 'tomica_model' and candidate.source_key.startswith('SP:'):
                from sqlalchemy import select
                from backend.app.models import SourceIdentity
                session = repository.session
                exact = session.scalar(select(SourceIdentity).where(SourceIdentity.source == 'tomica', SourceIdentity.kind == candidate.kind, SourceIdentity.source_key == candidate.source_key))
                if exact is not None:
                    return ResolvedIdentity(candidate.source_key)
                images = set(candidate.evidence.get('image_urls', []))
                identities = session.scalars(select(SourceIdentity).where(SourceIdentity.source == 'tomica', SourceIdentity.kind == 'tomica_model'))
                matches = {identity.entity_id for identity in identities if identity.source_key.startswith('SP:') and identity.evidence.get('url') == candidate.evidence.get('url') and identity.evidence.get('display_title') == candidate.evidence.get('display_title') and images.intersection(identity.evidence.get('image_urls', []))}
                if len(matches) > 1:
                    return ResolvedIdentity(None, [ParseIssue(code='IDENTITY_AMBIGUOUS', message='特别版图片证据对应多个条目', severity='error')])
                if matches:
                    session.add(SourceIdentity(source='tomica', kind=candidate.kind, source_key=candidate.source_key, entity_id=next(iter(matches)), evidence=candidate.evidence))
                    session.flush()
            return ResolvedIdentity(candidate.source_key)
        evidence = candidate.evidence
        if not evidence.get('url') or not evidence.get('model_key') or not evidence.get('image_url'):
            return ResolvedIdentity(None, [ParseIssue(code='IDENTITY_AMBIGUOUS', message='缺少稳定身份依据', url=evidence.get('url', ''), severity='error')])
        stable = {k: evidence[k] for k in ['url', 'model_key', 'image_url']}
        key = 'evidence:' + hashlib.sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest()
        candidate.source_key = key
        return ResolvedIdentity(key)
