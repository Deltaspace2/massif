"""Mont-Blanc Natural Resort — live lift status.

https://www.montblancnaturalresort.com/fr/infos-live

Note on the target: compagniedumontblanc.fr is the corporate/investor site and
carries no operational data. Same operator, different property. The live status
lives on montblancnaturalresort.com and is server-rendered, so selectolax is
enough — no Playwright.

EXTRACTION STRATEGY. The CSS selectors below are a best guess and have not been
calibrated against the live DOM. They are deliberately not load-bearing: if
they match nothing, the scraper falls back to a proximity scan that finds known
lift names in the page text and reads the nearest status word. The fallback is
uglier but survives a redesign, which the selectors will not.

Calibrate with:

    python -m massif.ingest.sources.mbnr_live --dump
"""

from __future__ import annotations

import re
import sys
from datetime import UTC, datetime

from selectolax.parser import HTMLParser
from sqlalchemy.orm import Session

from massif.enums import ExtractionMethod, StatementType, StatusValue
from massif.ingest.base import ExtractedStatement, Scraper, fetch, store_document
from massif.ingest.resolve import normalise
from massif.models import Document, Source

URL = "https://www.montblancnaturalresort.com/fr/infos-live"

# Best-guess selectors. Verify with --dump; the proximity fallback covers us
# until then.
ROW_SELECTORS = [
    "[class*='remontee']",
    "[class*='lift']",
    "[class*='status']",
    "[class*='ouverture']",
    "li[class*='item']",
]

# French status vocabulary -> our enum. Order matters: check negatives first,
# because "non ouvert" contains "ouvert".
STATUS_PATTERNS: list[tuple[re.Pattern, StatusValue, int]] = [
    (re.compile(r"\bnon\s+ouvert", re.I), StatusValue.CLOSED, 1),
    (re.compile(r"\bferm[ée]", re.I), StatusValue.CLOSED, 1),
    (re.compile(r"\bfermeture", re.I), StatusValue.CLOSED, 1),
    (re.compile(r"\bhors\s+service", re.I), StatusValue.CLOSED, 2),
    (re.compile(r"\bsuspendu", re.I), StatusValue.CLOSED, 2),
    (re.compile(r"\bouvert", re.I), StatusValue.OPEN, 0),
    (re.compile(r"\ben\s+service", re.I), StatusValue.OPEN, 0),
    (re.compile(r"\bouverture\s+pr[ée]vue", re.I), StatusValue.UNKNOWN, 0),
]

HOURS = re.compile(r"(\d{1,2})\s*[:hH]\s*(\d{2})\s*[-–—]\s*(\d{1,2})\s*[:hH]\s*(\d{2})")

# Lift names as this site writes them -> our feature slugs' surface forms. The
# resolver handles the rest; this is only the seed vocabulary for the
# proximity scan.
KNOWN_LIFTS = [
    "Aiguille du Midi",
    "Panoramic Mont-Blanc",
    "Montenvers",
    "Mer de Glace",
    "Brévent",
    "Flégère",
    "Grands Montets",
    "Balme",
    "Le Tour",
    "Vallorcine",
    "Les Houches",
    "Tramway du Mont-Blanc",
    "Les Bossons",
    "Megève",
    "La Vormaine",
]


def classify(text: str) -> tuple[StatusValue, int] | None:
    for pattern, status, severity in STATUS_PATTERNS:
        if pattern.search(text):
            return status, severity
    return None


def parse_hours(text: str) -> dict:
    match = HOURS.search(text)
    if not match:
        return {}
    o_h, o_m, c_h, c_m = match.groups()
    return {"first_lift": f"{int(o_h):02d}:{o_m}", "last_lift": f"{int(c_h):02d}:{c_m}"}


def _from_rows(tree: HTMLParser, observed_at: datetime) -> list[ExtractedStatement]:
    """Structured path: one element per lift."""
    out: list[ExtractedStatement] = []
    seen: set[str] = set()

    for selector in ROW_SELECTORS:
        for node in tree.css(selector):
            text = " ".join(node.text(separator=" ", strip=True).split())
            if not (8 < len(text) < 300):
                continue
            verdict = classify(text)
            if verdict is None:
                continue

            name = next(
                (lift for lift in KNOWN_LIFTS if normalise(lift) in normalise(text)),
                None,
            )
            if name is None or name in seen:
                continue
            seen.add(name)

            status, severity = verdict
            out.append(
                ExtractedStatement(
                    feature_mention=name,
                    statement_type=StatementType.OPERATIONAL_STATUS,
                    status=status,
                    severity=severity,
                    observed_at=observed_at,
                    summary_en=f"{name}: {status.value}",
                    original_text=text,
                    original_language="fr",
                    payload=parse_hours(text),
                    extraction_method=ExtractionMethod.RULE,
                    extraction_confidence=0.9,
                )
            )
        if out:
            break
    return out


def _from_proximity(tree: HTMLParser, observed_at: datetime) -> list[ExtractedStatement]:
    """Fallback: find each known lift name in the flattened text and read the
    nearest status word within a small window. Survives a redesign; less
    precise, so it is marked with lower confidence."""
    flat = " ".join(tree.text(separator=" ", strip=True).split())
    out: list[ExtractedStatement] = []

    for lift in KNOWN_LIFTS:
        index = normalise(flat).find(normalise(lift))
        if index < 0:
            continue
        # normalise() changes offsets, so re-find on the raw text
        raw_index = flat.lower().find(lift.lower())
        if raw_index < 0:
            continue
        window = flat[raw_index : raw_index + 160]
        verdict = classify(window)
        if verdict is None:
            continue
        status, severity = verdict
        out.append(
            ExtractedStatement(
                feature_mention=lift,
                statement_type=StatementType.OPERATIONAL_STATUS,
                status=status,
                severity=severity,
                observed_at=observed_at,
                summary_en=f"{lift}: {status.value}",
                original_text=window,
                original_language="fr",
                payload=parse_hours(window),
                extraction_method=ExtractionMethod.RULE,
                extraction_confidence=0.6,
                context="proximity fallback — selectors did not match",
            )
        )
    return out


class MbnrLiveScraper(Scraper):
    slug = "mbnr-live"

    def collect(
        self, session: Session, source: Source
    ) -> list[tuple[Document, list[ExtractedStatement]]]:
        response = fetch(URL)
        document, is_new = store_document(session, source, URL, response)
        if not is_new:
            return []  # page unchanged since last fetch

        observed_at = datetime.now(UTC)
        tree = HTMLParser(response.text)

        statements = _from_rows(tree, observed_at)
        if not statements:
            statements = _from_proximity(tree, observed_at)

        return [(document, statements)]


def _dump() -> int:
    """Print what the page actually looks like, so the selectors above can be
    replaced with real ones."""
    response = fetch(URL)
    tree = HTMLParser(response.text)

    print(f"HTTP {response.status_code}, {len(response.content)} bytes\n")

    print("--- elements whose text contains a status word ---")
    shown = 0
    for node in tree.css("*"):
        text = " ".join(node.text(separator=" ", strip=True).split())
        if not (8 < len(text) < 200) or classify(text) is None:
            continue
        if not any(normalise(lift) in normalise(text) for lift in KNOWN_LIFTS):
            continue
        print(f"  <{node.tag} class={node.attributes.get('class')!r}>")
        print(f"    {text[:160]}")
        shown += 1
        if shown >= 25:
            break
    if not shown:
        print("  none — the page shape has changed, or it is not server-rendered")

    print("\n--- lift names found in flat text ---")
    flat = normalise(" ".join(tree.text(separator=" ", strip=True).split()))
    for lift in KNOWN_LIFTS:
        print(f"  {'OK ' if normalise(lift) in flat else 'MISS'}  {lift}")
    return 0


if __name__ == "__main__":
    if "--dump" in sys.argv:
        raise SystemExit(_dump())
    print(__doc__)
