"""Hut seasons read off each hut's own website, by the model.

    python -m massif.ingest.sources.hut_sites        # dry run, no DB writes

WHY THIS IS THE LLM ONE. Thirty-seven wardened huts in this massif have no
published season we can reach, and they are on twenty-five separate websites
with nothing in common — no ids, no shared platform, no structure. That is the
case rules cannot do and the whole reason llm.py exists. Every structured
source stays on a rule parser and always will.

WHAT WAS MEASURED BEFORE ANY OF IT WAS BUILT, because the honest ceiling here
is much lower than the hut count suggests:

  robots.txt   23 of 25 hosts allow. refuge-lac-blanc.fr and
               www.rifugiogonella.com REFUSE and are not carried. Not worked
               around; base.fetch would refuse them anyway.
  readable     8 of 24 sites are JS-rendered and yield under 400 characters of
               prose — Montenvers gives 115. Nothing to read, so nothing here.
  language     11 of the 15 readable sites are French, including the four
               Suisse-romande CAS huts. Only four are Italian, and fr_dates
               cannot read Italian, so those arrive undated and are demoted.
  URLs         camptocamp supplies them and at least two were wrong. They are
               curated in features_curated.yaml and checked, never trusted.

WHICH HUT A STATEMENT IS ABOUT. Not simply "the one whose site it is". The
Cabane d'Orny's page carries a sentence about the Cabane de l'A Neuve, and
pinning everything to the site's owner would have filed A Neuve's closure on
Orny. So the mention is resolved against huts first, exactly as any other
source, and only an UNRESOLVED mention falls back to the site's own hut —
because "la cabane" on a one-hut website means that hut, and that is the one
inference this source is entitled to make.

THE YEAR IS USUALLY OURS. These pages say "du 15 mars au 15 octobre" and mean
every year. `read_document` is given the document's year to bind such phrases
to, and the resulting statements carry `approximate` so nothing prints them as
dates the operator published. A phrase that states its own year is never
second-guessed.

EVERYTHING HERE IS needs_review. No statement from this source can take a
status slot until a person clears it. At twenty-odd sites a week that is a
review queue, not a safety net, and it is the reason this is deliberately
pointed at a handful of curated huts rather than every site that would answer.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from massif.db import session_scope
from massif.ingest.base import ExtractedStatement, Scraper, fetch, store_document
from massif.ingest.llm import read_document, readable_text
from massif.ingest.llm_client import build_extractor
from massif.ingest.resolve import FeatureResolver
from massif.models import Document, Feature, Source

# The most prose we will pay to read from one page. Every site measured came in
# well under this; the cap is here so a redesign that inlines a blog archive
# cannot quietly turn one hut into a large bill.
MAX_CHARS = 20000

# Under this there is no page worth reading — the site is JS-rendered and the
# prose is a cookie banner. Logged rather than skipped silently, because "this
# hut produces nothing" and "this hut could not be fetched" are different
# facts and only one of them is about the hut.
MIN_CHARS = 400

SEEDS = Path(__file__).resolve().parents[3] / "seeds" / "hut_sites.yaml"


def hut_sites() -> dict[str, str]:
    """slug -> the hut's own page. The entire configuration of this source.

    A hut absent from the file is never fetched, which is how robots refusals,
    JS-only sites and huts already covered by a better source stay out — each
    with its reason written beside it.
    """
    if not SEEDS.exists():
        return {}
    return yaml.safe_load(SEEDS.read_text(encoding="utf-8")) or {}


class HutSiteScraper(Scraper):
    slug = "hut-sites"

    def __init__(self) -> None:
        self._huts: FeatureResolver | None = None

    # ------------------------------------------------------------ collecting

    def collect(
        self, session: Session, source: Source
    ) -> list[tuple[Document, list[ExtractedStatement]]]:
        extractor = build_extractor(session)
        if extractor is None:
            # Same contract as a source with no registered scraper: skipped,
            # never half-run. A machine without a key must complete.
            print("  no ANTHROPIC_API_KEY — hut-sites skipped, not failed")
            return []

        out: list[tuple[Document, list[ExtractedStatement]]] = []
        sites = hut_sites()
        for hut in session.scalars(
            select(Feature)
            .where(Feature.feature_type == "hut", Feature.active.is_(True))
            .order_by(Feature.slug)
        ):
            url = sites.get(hut.slug)
            if not url:
                continue
            try:
                response = fetch(url)
            except Exception as error:  # noqa: BLE001 — one dead site is not a run
                print(f"  ! {hut.slug}: {type(error).__name__}: {error}")
                continue
            document, _ = store_document(session, source, url, response)
            out.append((document, self._read(document, extractor, hut.slug)))
        return out

    # ------------------------------------------------------------ extracting

    def _read(self, document: Document, extractor, own_slug: str | None):
        raw_html = document.raw_text or (document.raw_content or b"").decode("utf-8", "replace")
        prose = readable_text(raw_html)[:MAX_CHARS]
        if len(prose) < MIN_CHARS:
            print(f"  - {document.url}: {len(prose)} chars of prose, nothing to read")
            return []

        observed = document.published_at or document.fetched_at
        reading = read_document(
            extractor.extract(prose),
            prose,
            observed,
            model=extractor.model,
            source_url=document.url,
            # These pages state a recurring season without a year.
            assume_year=observed.year,
        )
        for rejection in reading.rejected:
            print(f"  - {document.url}: [{rejection.reason}] {rejection.detail[:70]}")
        for statement in reading.statements:
            if own_slug:
                statement.payload["site_of"] = own_slug
        return reading.statements

    def extract_stored(self, document: Document) -> list[ExtractedStatement]:
        """Re-read one stored page.

        The cache lives in its own session on purpose: it is a memo table, not
        part of whatever transaction is re-extracting, and `reextract` hands
        this method a document and no session. Without it a re-run over stored
        history would pay for every page again, which is the one thing storing
        them was supposed to prevent.
        """
        with session_scope() as cache_session:
            extractor = build_extractor(cache_session)
            if extractor is None:
                print("  no ANTHROPIC_API_KEY — nothing to re-extract")
                return []
            own = cache_session.scalar(
                select(Feature.slug).where(Feature.external_ids["hut_site"].astext == document.url)
            )
            return self._read(document, extractor, own)

    # -------------------------------------------------------------- resolving

    def resolve_and_build(self, session, source, document, item, resolver):
        """Resolve the mention against huts; fall back to the site's own hut.

        The Cabane d'Orny's page carries a sentence about the Cabane de l'A
        Neuve. Pinning every statement to the site's owner would have filed
        that closure on Orny, so a mention that resolves goes where it
        resolves. Only an unresolved one — "la cabane", "le refuge" — falls
        back, because on a one-hut website that is what those words mean.
        """
        from massif.ingest.sources.ffcam import HutResolver

        if self._huts is None:
            self._huts = HutResolver(session)

        match, _ = self._huts.resolve(item.feature_mention)
        if match is not None:
            feature = session.get(Feature, match.feature_id)
            if feature is not None:
                item.feature_slug = feature.slug
        elif item.payload.get("site_of"):
            item.feature_slug = item.payload["site_of"]
            item.payload["attributed_by"] = "the site it was published on"
        return super().resolve_and_build(session, source, document, item, resolver)


def _dump() -> int:
    """What the model makes of the live pages, writing no statements."""
    with session_scope() as session:
        extractor = build_extractor(session)
        if extractor is None:
            print("no ANTHROPIC_API_KEY — nothing to dump")
            return 1
        scraper = HutSiteScraper()
        now = datetime.now(UTC)
        sites = hut_sites()
        seen = 0
        for hut in session.scalars(
            select(Feature)
            .where(Feature.feature_type == "hut", Feature.active.is_(True))
            .order_by(Feature.slug)
        ):
            url = sites.get(hut.slug)
            if not url:
                continue
            seen += 1
            try:
                response = fetch(url)
            except Exception as error:  # noqa: BLE001
                print(f"  ! {hut.slug}: {type(error).__name__}: {error}")
                continue

            class Fetched:
                raw_text = response.text
                raw_content = None
                published_at = None
                fetched_at = now

            Fetched.url = url
            for statement in scraper._read(Fetched, extractor, hut.slug):
                window = (
                    f"{statement.valid_from:%d %b} – {statement.valid_to:%d %b %Y}"
                    if statement.valid_from and statement.valid_to
                    else "UNDATED"
                )
                flag = " ~approx" if statement.payload.get("approximate") else ""
                print(
                    f"  {hut.slug[:24]:26} {statement.status.value:8} "
                    f"{statement.feature_mention[:26]:28} {window}{flag}"
                )
        print(f"\n{seen} of {len(hut_sites())} listed huts were reachable")
    return 0


if __name__ == "__main__":
    raise SystemExit(_dump())
