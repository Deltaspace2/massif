"""Ingest pipeline primitives.

Four stages, each independently re-runnable. Never fuse them:

    fetch -> store document -> extract statements -> resolve -> recompute

Conduct: honour robots.txt, identify with a real User-Agent and contact URL,
rate-limit hard, back off on errors. You are a guest on these servers.
"""

from __future__ import annotations

import hashlib
import time
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
from massif.models import Document, IngestRun, Source, Statement
from massif.ingest.resolve import FeatureResolver
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
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    summary_en: str | None = None
    original_text: str | None = None
    original_language: str | None = None
    payload: dict = field(default_factory=dict)
    extraction_method: ExtractionMethod = ExtractionMethod.RULE
    extraction_confidence: float | None = None
    context: str | None = None


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
