"""Ingest pipeline primitives.

Four stages, each independently re-runnable. Never fuse them:

    fetch -> store document -> extract statements -> resolve -> recompute

Conduct: honour robots.txt, identify with a real User-Agent and contact URL,
rate-limit hard, back off on errors. You are a guest on these servers.
"""

from __future__ import annotations

import hashlib
import re
import time
import unicodedata
import urllib.robotparser
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from massif.config import settings
from massif.enums import ExtractionMethod, StatementType, StatusValue
from massif.models import Document, Feature, IngestRun, Source, Statement
from massif.ingest.resolve import FeatureResolver, Match, normalise
from massif.status import recompute_many

_last_request_at: dict[str, float] = defaultdict(float)
_robots_cache: dict[str, urllib.robotparser.RobotFileParser] = {}


def _throttle(host: str) -> None:
    elapsed = time.monotonic() - _last_request_at[host]
    wait = settings.scrape_min_interval - elapsed
    if wait > 0:
        time.sleep(wait)
    _last_request_at[host] = time.monotonic()


def robots_allows(url: str) -> bool:
    parsed = urlparse(url)
    root = f"{parsed.scheme}://{parsed.netloc}"
    parser = _robots_cache.get(root)
    if parser is None:
        parser = urllib.robotparser.RobotFileParser()
        parser.set_url(f"{root}/robots.txt")
        try:
            parser.read()
        except Exception:
            # No reachable robots.txt: proceed, but stay slow and polite.
            _robots_cache[root] = parser
            return True
        _robots_cache[root] = parser
    return parser.can_fetch(settings.user_agent, url)


def fetch(url: str, *, client: httpx.Client | None = None) -> httpx.Response:
    if not robots_allows(url):
        raise PermissionError(f"robots.txt disallows {url}")
    host = urlparse(url).netloc
    _throttle(host)
    owned = client is None
    client = client or httpx.Client(
        headers={"User-Agent": settings.user_agent},
        timeout=settings.scrape_timeout,
        follow_redirects=True,
    )
    try:
        response = client.get(url)
        response.raise_for_status()
        return response
    finally:
        if owned:
            client.close()


def store_document(
    session: Session,
    source: Source,
    url: str,
    response: httpx.Response,
    *,
    raw_text: str | None = None,
    published_at: datetime | None = None,
) -> tuple[Document, bool]:
    """Returns (document, is_new). Unchanged content writes no new row."""
    content_hash = hashlib.sha256(response.content).hexdigest()

    existing = session.scalar(
        select(Document).where(
            Document.source_id == source.id, Document.content_hash == content_hash
        )
    )
    if existing is not None:
        return existing, False

    document = Document(
        source_id=source.id,
        url=url,
        content_hash=content_hash,
        content_type=response.headers.get("content-type"),
        raw_content=response.content,
        raw_text=raw_text if raw_text is not None else _maybe_text(response),
        language_detected=source.language,
        http_status=response.status_code,
        published_at=published_at,
    )
    session.add(document)
    session.flush()
    return document, True


def _maybe_text(response: httpx.Response) -> str | None:
    ctype = response.headers.get("content-type", "")
    if "text" in ctype or "json" in ctype or "xml" in ctype:
        return response.text
    return None


@dataclass
class ExtractedStatement:
    """What a scraper produces. Feature is still a name, not an id — the
    resolver turns it into one."""

    feature_mention: str
    statement_type: StatementType
    status: StatusValue
    observed_at: datetime
    severity: int = 0
    # Set when the source exposes a stable identifier (an element id, an
    # API key) mapped to a feature slug. Exact lookup, no fuzzy matching —
    # a source that knows what it is should never be guessed at.
    feature_slug: str | None = None
    # Set when the source is authoritative about a parent/child hierarchy —
    # an operator listing the lifts inside its own sector. Resolution is then
    # restricted to that parent's children, and a child is created on first
    # sight rather than fuzzy-matched against the whole table. Without this,
    # "TC MER DE GLACE" cheerfully resolves to the Mer de Glace glacier.
    parent_slug: str | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    summary_en: str | None = None
    original_text: str | None = None
    original_language: str | None = None
    payload: dict = field(default_factory=dict)
    extraction_method: ExtractionMethod = ExtractionMethod.RULE
    extraction_confidence: float | None = None
    context: str | None = None


def slugify(text: str) -> str:
    """ASCII slug for auto-provisioned features."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return re.sub(r"-{2,}", "-", text)


def resolve_child(session: Session, parent_slug: str, name: str) -> "Match | None":
    """Find (or create) the child of parent_slug named `name`.

    Scoped so a lift can never resolve to an unrelated feature, and
    auto-provisioning because the operator is the authority on which lifts
    exist inside its own sector. Created features carry no geometry and are
    marked so a human can see what the machine invented.
    """
    parent = session.scalar(select(Feature).where(Feature.slug == parent_slug))
    if parent is None:
        return None

    target = normalise(name)
    for child in session.scalars(
        select(Feature).where(Feature.parent_id == parent.id)
    ):
        forms = [child.name_default, *(child.aliases or [])]
        if any(normalise(f) == target for f in forms):
            return Match(str(child.id), 100.0, child.name_default)

    child = Feature(
        slug=f"{parent_slug}-{slugify(name)}",
        feature_type=parent.feature_type,
        name_default=name,
        names={},
        aliases=[name],
        parent_id=parent.id,
        massif=parent.massif,
        country=parent.country,
        external_ids={},
        notes=f"Auto-created from an operator feed as a child of {parent_slug}.",
    )
    session.add(child)
    session.flush()
    return Match(str(child.id), 100.0, name)


class Scraper(ABC):
    """One per source. Implement collect(); the base class handles storage,
    resolution and status recomputation."""

    slug: str

    @abstractmethod
    def collect(
        self, session: Session, source: Source
    ) -> list[tuple[Document, list[ExtractedStatement]]]:
        """Fetch, store documents, and extract statements from them."""

    def run(self, session: Session) -> IngestRun:
        source = session.scalar(select(Source).where(Source.slug == self.slug))
        if source is None:
            raise LookupError(f"source {self.slug!r} not seeded")

        run = IngestRun(source_id=source.id)
        session.add(run)
        session.flush()

        resolver = FeatureResolver(session)
        touched: set = set()

        try:
            for document, extracted in self.collect(session, source):
                run.documents_new += 1
                for item in extracted:
                    if item.parent_slug:
                        match = resolve_child(
                            session, item.parent_slug, item.feature_mention
                        )
                        candidates = []
                        if match is None:
                            resolver.queue_unresolved(
                                item.feature_mention,
                                [],
                                source_id=source.id,
                                document_id=document.id,
                                context=f"parent {item.parent_slug} not seeded",
                            )
                            run.unresolved_new += 1
                            continue
                    elif item.feature_slug:
                        feature = session.scalar(
                            select(Feature).where(Feature.slug == item.feature_slug)
                        )
                        match = (
                            Match(str(feature.id), 100.0, item.feature_slug)
                            if feature
                            else None
                        )
                        candidates = []
                    else:
                        match, candidates = resolver.resolve(item.feature_mention)

                    if match is None:
                        resolver.queue_unresolved(
                            item.feature_mention,
                            candidates,
                            source_id=source.id,
                            document_id=document.id,
                            context=item.context or item.original_text,
                        )
                        run.unresolved_new += 1
                        continue

                    session.add(
                        Statement(
                            feature_id=match.feature_id,
                            source_id=source.id,
                            document_id=document.id,
                            statement_type=item.statement_type,
                            status=item.status,
                            severity=item.severity,
                            observed_at=item.observed_at,
                            valid_from=item.valid_from,
                            valid_to=item.valid_to,
                            summary_en=item.summary_en,
                            original_text=item.original_text,
                            original_language=item.original_language or source.language,
                            payload=item.payload,
                            extraction_method=item.extraction_method,
                            extraction_confidence=item.extraction_confidence,
                        )
                    )
                    run.statements_new += 1
                    touched.add(match.feature_id)

                document.extracted_at = datetime.now(UTC)

            session.flush()
            recompute_many(session, touched)

            run.ok = True
            source.last_success_at = datetime.now(UTC)
            source.consecutive_failures = 0
            source.last_error = None
        except Exception as exc:
            run.ok = False
            run.error = f"{type(exc).__name__}: {exc}"
            source.consecutive_failures += 1
            source.last_error = run.error
            raise
        finally:
            run.finished_at = datetime.now(UTC)
            source.last_fetch_at = datetime.now(UTC)

        return run
