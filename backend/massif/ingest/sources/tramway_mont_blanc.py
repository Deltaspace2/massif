"""Tramway du Mont-Blanc — the operator's published running periods.

    python -m massif.ingest.sources.tramway_mont_blanc     # dry run, no DB

WHY A SEPARATE SOURCE FROM mbnr-openings. The Tramway is Compagnie du
Mont-Blanc's, but neither of the pages we already read publishes it. Both
`infos-live` and `annual-openings` contain the string "Tramway du Mont-Blanc"
against the slug `tramway-montblanc`, which looks exactly like a row we are
dropping; it is only an entry in the RSC payload's table of display labels,
with nothing behind it. The link on that slug leaves the site entirely, for
tramwaydumontblanc.fr, which is where the running periods actually live.

That matters more than it sounds. The Tramway is the access for the Goûter
route — our own seed note says "its closure closes the normal approach" — and
until now it was a feature we carried with no source watching it at all.

WHAT IS PARSED. `select.tmb-periode-select`, whose options are the season's
running periods: "Du 31/08/2026 au 27/09/2026". The same strings appear again
in the page's Elementor tab markup; this reads the purpose-built `tmb-` element
rather than the page builder's generic output, because one of those two is
about this railway and the other is about whoever laid the page out.

WHY `UNKNOWN` AND NOT `OPEN`. This follows mbnr-openings, not ffcam-refuges,
and the difference is what the source is claiming. FFCAM states that a hut is
open to the public on given dates and takes bookings against it. A timetable
states when trains are scheduled to run, which is not an observation that one
is running — and this railway stops for weather. The operator says as much,
though only in the ticket-refund FAQ ("sauf contrainte technique ou
météorologique où nous serions fermés"), which is why that sentence is NOT
reproduced as a caveat on the schedule: it is a refund condition, and dressing
it up as a service warning would be us putting words in their mouth.

An OPENING at UNKNOWN is not a wasted statement. It feeds `season` — the
"availability this season, ignoring the hour" field a trip planner actually
asks — which is how La Vormaine correctly reads "not running this season" in
September without a red dot, and how the Tramway now reads as running without
a green one.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from selectolax.parser import HTMLParser
from sqlalchemy.orm import Session

from massif.enums import ExtractionMethod, StatementType, StatusValue
from massif.ingest.base import ExtractedStatement, Scraper, fetch, store_document
from massif.ingest.fr_dates import describe, parse_range
from massif.models import Document, Source

HOME = "https://www.tramwaydumontblanc.fr/"

# The operator's own single-feature site. There is nothing to fuzzy-match:
# never guess at what a source tells you outright.
TARGET_SLUG = "tramway-du-mont-blanc"

PERIOD_SELECT = "select.tmb-periode-select option"
PERIOD = re.compile(r"\bDu\s+\d{1,2}/\d{1,2}/\d{4}\s+au\s+\d{1,2}/\d{1,2}/\d{4}\b")


def periods(html: str) -> list[str]:
    """The running-period strings the operator publishes, in page order.

    Deduplicated. The page's tab markup repeats these strings, but that is not
    what this reads, so the dedupe is guarding the narrower case of a select
    that repeats an option itself — cheap, and a period counted twice writes
    two statements that supersede each other on every run.
    """
    out: list[str] = []
    for option in HTMLParser(html).css(PERIOD_SELECT):
        found = PERIOD.search(" ".join(option.text().split()))
        if found and found.group(0) not in out:
            out.append(found.group(0))
    return out


def extract(html: str, observed_at: datetime) -> list[ExtractedStatement]:
    out: list[ExtractedStatement] = []
    for text in periods(html):
        window = parse_range(text)
        if window is None or window.start is None or window.end is None:
            # Kept visible rather than dropped: a period we cannot read is the
            # page having changed shape, which is the moment to look at it.
            print(f"  - unparseable running period: {text!r}")
            continue
        out.append(
            ExtractedStatement(
                feature_mention="Tramway du Mont-Blanc",
                feature_slug=TARGET_SLUG,
                statement_type=StatementType.OPENING,
                # A timetable says what is scheduled, never what is running.
                status=StatusValue.UNKNOWN,
                severity=0,
                observed_at=observed_at,
                valid_from=window.start,
                valid_to=window.end,
                summary_en=(
                    f"Scheduled to run {describe(window)}"
                    " (operator timetable, not a report that it is running)"
                ),
                original_text=text,
                original_language="fr",
                extraction_method=ExtractionMethod.RULE,
                payload={"schedule": True, "period": text},
            )
        )
    return out


class TramwayMontBlancScraper(Scraper):
    slug = "tmb-tramway"

    def collect(
        self, session: Session, source: Source
    ) -> list[tuple[Document, list[ExtractedStatement]]]:
        response = fetch(HOME)
        document, _ = store_document(session, source, HOME, response)
        found = extract(response.text, document.fetched_at)
        if not found:
            # No silent caps. An empty run here means the selector stopped
            # matching, and a source that quietly returns nothing looks
            # identical to a railway that publishes nothing.
            print(f"  ! no running periods found at {HOME} — has the page changed?")
        return [(document, found)]

    def extract_stored(self, document: Document) -> list[ExtractedStatement]:
        raw = document.raw_text or (document.raw_content or b"").decode("utf-8", "replace")
        return extract(raw, document.published_at or document.fetched_at)


def _dump() -> int:
    """What the parser makes of the live page, writing nothing."""
    response = fetch(HOME)
    found = extract(response.text, datetime.now(UTC))
    now = datetime.now(UTC)
    print(f"{len(found)} running periods at {HOME}\n")
    for statement in found:
        live = statement.valid_from <= now <= statement.valid_to
        print(
            f"  {statement.original_text:34} {statement.summary_en}"
            f"{'   <- covers today' if live else ''}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(_dump())
