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
from massif.ingest.resolve import FeatureResolver, Match, normalise
from massif.models import Document, Feature, IngestRun, Source, Statement
from massif.status import recompute_many

_last_request_at: dict[str, float] = defaultdict(float)

# root -> (monotonic time of the check, parser or None if it could not be read)
_robots_cache: dict[
    str, tuple[float, urllib.robotparser.RobotFileParser | None]
] = {}

# How long a robots.txt verdict is reused before re-fetching.
ROBOTS_TTL = 3600.0
ROBOTS_RETRY_TTL = 300.0


def _throttle(host: str) -> None:
    elapsed = time.monotonic() - _last_request_at[host]
    wait = settings.scrape_min_interval - elapsed
    if wait > 0:
        time.sleep(wait)
    _last_request_at[host] = time.monotonic()


def _read_robots(root: str) -> urllib.robotparser.RobotFileParser | None:
    """Fetch and parse one robots.txt. None means we could not find out.

    Fetched with httpx rather than RobotFileParser.read(), which uses
    urllib with no timeout and sends `Python-urllib/x.y` instead of the
    User-Agent we promise to identify with — announcing ourselves honestly
    matters most on the request that asks what we are allowed to do.
    """
    parser = urllib.robotparser.RobotFileParser()
    try:
        response = httpx.get(
            f"{root}/robots.txt",
            headers={"User-Agent": settings.user_agent},
            timeout=settings.scrape_timeout,
            follow_redirects=True,
        )
    except Exception:
        return None

    code = response.status_code
    if code in (401, 403):
        # Access to the policy itself is restricted: treat the whole site as
        # off limits rather than guessing we are welcome.
        parser.disallow_all = True
        return parser
    if 400 <= code < 500:
        # No robots.txt published. Nothing is disallowed.
        parser.allow_all = True
        return parser
    if code >= 500:
        # The server is struggling. Hammering it is the worst possible reply.
        return None

    parser.parse(response.text.splitlines())
    return parser


def robots_allows(url: str) -> bool:
    """May we fetch this URL?

    Unreachable robots.txt means NO, not yes. The previous version returned
    True on any exception and then cached a parser it had never read — and
    `can_fetch` on an unread parser returns False. So the first request to a
    host with a flaky robots.txt was permitted and every later one refused,
    for the life of the process, with no retry. Chamonix was written off as
    "recon blocked" on the strength of one 503 that had long since cleared.
    """
    parsed = urlparse(url)
    root = f"{parsed.scheme}://{parsed.netloc}"
    now = time.monotonic()

    cached = _robots_cache.get(root)
    if cached is not None:
        checked_at, parser = cached
        # A failure is re-checked sooner than a success: a 503 is usually a
        # bad minute, not a policy, and must not poison the host until
        # restart. A published policy is stable enough to reuse for an hour.
        ttl = ROBOTS_TTL if parser is not None else ROBOTS_RETRY_TTL
        if now - checked_at < ttl:
            return parser.can_fetch(settings.user_agent, url) if parser else False

    parser = _read_robots(root)
    _robots_cache[root] = (now, parser)
    if parser is None:
        return False
    return parser.can_fetch(settings.user_agent, url)


def fetch(url: str, *, client: httpx.Client | None = None) -> httpx.Response:
    if not robots_allows(url):
        raise PermissionError(
            f"robots.txt disallows {url} (or could not be read — an "
            f"unreachable policy is treated as a refusal)"
        )
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


def resolve_child(session: Session, parent_slug: str, name: str) -> Match | None:
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


def retire_replaced(session: Session, incoming: Statement) -> int:
    """Mark older readings that this statement replaces as superseded.

    A source reporting on a feature again has not added a second opinion; it
    has updated its own. Without this, every reading from every run stayed
    permanently live — harmless while nothing read them, then visible as
    "3 other current notices" on every lift the moment the API started
    surfacing non-winning statements.

    Same feature, same source, same type, and overlapping validity. The
    overlap test is what keeps mbnr-openings' summer and winter seasons apart:
    both OPENING, both from one source on one feature, but two different facts
    rather than two readings of one.
    """
    query = select(Statement).where(
        Statement.feature_id == incoming.feature_id,
        Statement.source_id == incoming.source_id,
        Statement.statement_type == incoming.statement_type,
        Statement.superseded_at.is_(None),
        Statement.superseded_by.is_(None),
    )
    if incoming.valid_from is not None:
        query = query.where(
            (Statement.valid_to.is_(None))
            | (Statement.valid_to >= incoming.valid_from)
        )
    if incoming.valid_to is not None:
        query = query.where(
            (Statement.valid_from.is_(None))
            | (Statement.valid_from <= incoming.valid_to)
        )

    now = datetime.now(UTC)
    count = 0
    for older in session.scalars(query):
        if (
            older.observed_at
            and incoming.observed_at
            and older.observed_at > incoming.observed_at
        ):
            continue  # the stored one is newer; leave it alone
        older.superseded_at = now
        count += 1

    count += _lift_undated_closures(session, incoming, now)
    return count


def lift_undated_closures(
    session: Session,
    feature_id,
    source_id,
    published_at: datetime,
    now: datetime,
) -> int:
    """Retire undated closures on one feature/source older than `published_at`.

    Factored out of retire_replaced because re-extraction needs it too and did
    not have it: reextract.py retires per DOCUMENT and inserts fresh rows, so
    it never went through retire_replaced at all. Re-extracting Saint-Gervais
    therefore resurrected the 11 August rockfall closure every time, under a
    headline that correctly said the route reopened on the 26th.
    """
    stale_closures = select(Statement).where(
        Statement.feature_id == feature_id,
        Statement.source_id == source_id,
        Statement.statement_type == StatementType.CLOSURE,
        Statement.valid_from.is_(None),
        Statement.valid_to.is_(None),
        Statement.observed_at < published_at,
        Statement.superseded_at.is_(None),
        Statement.superseded_by.is_(None),
    )
    count = 0
    for closure in session.scalars(stale_closures):
        closure.superseded_at = now
        count += 1
    return count


def _lift_undated_closures(
    session: Session, incoming: Statement, now: datetime
) -> int:
    """An opening retires the undated closures the same authority left standing.

    The type match above is deliberate — one source updating its own reading of
    one thing — but it means a closure is never a candidate for retirement by an
    opening, and an undated closure has no validity window to expire either. So
    it stands forever.

    Saint-Gervais shut access to Mont Blanc on 11 August over lethal rockfall
    and reopened the Tête Rousse and Goûter refuges on the 26th. The closure was
    still being served as "currently in force" on the 30th, under a headline
    that correctly said the route was open. That is precisely the confidently
    contradictory page this project exists to avoid.

    Deliberately narrow: same feature, same source, closure only, undated only,
    and only where the opening genuinely post-dates it. A closure carrying its
    own dates expires on its own terms and is none of this function's business.
    """
    if incoming.statement_type != StatementType.OPENING:
        return 0
    if incoming.observed_at is None:
        return 0
    return lift_undated_closures(
        session,
        incoming.feature_id,
        incoming.source_id,
        incoming.observed_at,
        now,
    )


class Scraper(ABC):
    """One per source. Implement collect(); the base class handles storage,
    resolution and status recomputation."""

    slug: str

    @abstractmethod
    def collect(
        self, session: Session, source: Source
    ) -> list[tuple[Document, list[ExtractedStatement]]]:
        """Fetch, store documents, and extract statements from them."""

    def extract_stored(self, document: Document) -> list[ExtractedStatement]:
        """Re-run extraction over an already-stored document, no network.

        The extract half of `collect()`, callable on `document.raw_text`.
        Implementing this is what lets an improved parser be re-run over
        history instead of re-fetching it — see massif.scripts.reextract.

        `observed_at` must come from the document, never from now(): a
        re-extraction is not a new observation, and dating April's notice
        today would hand it the ranking win over August's.
        """
        raise NotImplementedError(
            f"{type(self).__name__} has no extract_stored(); "
            f"it cannot be re-extracted from stored documents yet"
        )

    def resolve_and_build(
        self,
        session: Session,
        source: Source,
        document: Document,
        item: ExtractedStatement,
        resolver: FeatureResolver,
    ) -> Statement | None:
        """Resolve one extracted item to a feature and build its Statement.

        Returns None when the mention did not resolve, having queued it in
        `unresolved_mentions` first — unmatched goes to the review queue,
        never to /dev/null.

        Shared by `run()` and by re-extraction so the resolution rules cannot
        drift apart between the two paths.
        """
        if item.parent_slug:
            match = resolve_child(session, item.parent_slug, item.feature_mention)
            candidates = []
            if match is None:
                resolver.queue_unresolved(
                    item.feature_mention,
                    [],
                    source_id=source.id,
                    document_id=document.id,
                    context=f"parent {item.parent_slug} not seeded",
                )
                return None
        elif item.feature_slug:
            feature = session.scalar(
                select(Feature).where(Feature.slug == item.feature_slug)
            )
            match = (
                Match(str(feature.id), 100.0, item.feature_slug) if feature else None
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
            return None

        return Statement(
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
                    statement = self.resolve_and_build(
                        session, source, document, item, resolver
                    )
                    if statement is None:
                        run.unresolved_new += 1
                        continue
                    retire_replaced(session, statement)
                    session.add(statement)
                    run.statements_new += 1
                    touched.add(statement.feature_id)

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
