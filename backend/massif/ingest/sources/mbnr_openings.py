"""Mont-Blanc Natural Resort — seasonal opening calendar.

https://www.montblancnaturalresort.com/fr/ouvertures

Forward-looking counterpart to mbnr_live. Live status answers "is it running
now"; this answers "will the Tramway be running in late September" — the
question you actually ask when planning, and one no live feed can answer.

WHY THIS PARSES JSON AND NOT HTML. The page is a Next.js app and ships its
content as structured data inside the RSC flight payload:

    {"_modelApiKey": "block_table", "seasonType": "winter",
     "table": [{"startDate": "2026-11-01", "endDate": "2027-05-31",
                "list": [...
       {"__typename": "TableLineDateRecord",
        "title": "Aiguille du Midi",
        "subtitle": "Chamonix Mont-Blanc - 3842 m",
        "valueOne": "2026-12-19", "valueTow": "2027-05-30"}

ISO dates, both seasons, altitudes. Scraping the rendered table instead would
mean parsing localised dates, and recon showed why that is dangerous: the
English page renders 1 May 2026 as "5/1/2026" while the French renders it
"01/05/2026". Cross-checking 13/07 against 7/13 is what proved the English
page is US-format — there is no month 13. Reading the JSON removes the whole
class of error.

("valueTow" is their typo for Two. Inherited, not corrected — matching the
source exactly is worth more than tidiness.)

Statements carry valid_from/valid_to rather than describing the present, so a
future season lies dormant until its own start date. recompute_feature already
filters on validity; no scheduling logic is needed here.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from datetime import time as dtime
from typing import Any

from sqlalchemy.orm import Session

from massif.enums import ExtractionMethod, StatementType, StatusValue
from massif.ingest.base import ExtractedStatement, Scraper, fetch, store_document
from massif.ingest.fr_dates import strip_accents
from massif.models import Document, Source

URL = "https://www.montblancnaturalresort.com/fr/ouvertures"

# Row title -> feature slug. Titles, not ids, so this is explicit. Anything
# absent falls through to the fuzzy resolver and then the review queue, which
# is where a newly added site should surface.
SECTOR_FEATURES: dict[str, str] = {
    "aiguille du midi": "aiguille-du-midi",
    "panoramic mont-blanc": "panoramic-mont-blanc",
    "montenvers - mer de glace": "montenvers-railway",
    "montenvers": "montenvers-railway",
    "brévent": "brevent",
    "flégère": "flegere",
    "balme": "balme-le-tour",
    "balme (le tour et vallorcine)": "balme-le-tour",
    "balme (le tour - vallorcine)": "balme-le-tour",
    "grands montets": "grands-montets",
    "les houches": "les-houches",
    "tramway du mont-blanc": "tramway-du-mont-blanc",
    "les planards": "les-planards",
    "megève": "megeve-rochebrune",
    "megève - rochebrune": "megeve-rochebrune",
    "megève - mont d'arbois": "megeve-mont-arbois",
    "la vormaine": "la-vormaine",
    "les bossons": "telesiege-des-bossons",
}

# Some titles are ambiguous and the subtitle is the discriminator. Balme
# publishes two summer seasons under one title because the operator genuinely
# runs its two sides on different dates — Le Tour 20 Jun-20 Sep, Vallorcine
# 4 Jul-13 Sep — and combines them in winter. Without this, both land on the
# sector and compete for one status slot all summer.
#
# Checked before SECTOR_FEATURES. (title, substring of subtitle) -> slug.
# Matched on how the subtitle STARTS, not on substring containment. The first
# version used `in` and filed the combined winter season — subtitle "Le Tour -
# Vallorcine - 2270 m" — against the Vallorcine gondola alone, because
# "vallorcine" appears inside it. Anchoring removes the ordering hazard
# entirely rather than relying on the list staying in the right order.
SUBTITLE_OVERRIDES: list[tuple[str, str, str]] = [
    ("balme", "le tour - vallorcine", "balme-le-tour"),
    ("balme", "le tour", "balme-le-tour"),
    ("balme", "vallorcine", "balme-le-tour-tc-vallorcine"),
]


# One calendar row can cover several sectors. "Megève", subtitle "Evasion
# Mont-Blanc -2350 m", is the linked domain — it is about Megève, and both our
# Megève sectors are Megève. Mapping it to Rochebrune alone left Mont d'Arbois
# with no season at all and grey on a map that colours by season, which read
# as "we have no idea" when the operator had in fact published one.
MULTI_TARGETS: dict[str, list[str]] = {
    "megeve": ["megeve-rochebrune", "megeve-mont-arbois"],
}


def resolve_slugs(title: str, subtitle: str) -> list[str]:
    """Every feature this row speaks for. Usually one; sometimes a domain."""
    # strip_accents, because the key is "megeve" and the title is "Megève".
    # Fourth time an accent has silently broken a match in this project.
    multi = MULTI_TARGETS.get(strip_accents(title).lower().strip())
    if multi:
        return multi
    single = resolve_slug(title, subtitle)
    return [single] if single else []


def resolve_slug(title: str, subtitle: str) -> str | None:
    low_title, low_sub = title.lower().strip(), subtitle.lower().strip()
    # longest prefix wins, so "le tour - vallorcine" beats "le tour"
    best: tuple[int, str] | None = None
    for want_title, want_sub, slug in SUBTITLE_OVERRIDES:
        if (
            low_title == want_title
            and low_sub.startswith(want_sub)
            and (best is None or len(want_sub) > best[0])
        ):
            best = (len(want_sub), slug)
    if best:
        return best[1]
    return SECTOR_FEATURES.get(low_title)


ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ALTITUDE = re.compile(r"(\d{3,4})\s*m\b")

_decoder = json.JSONDecoder()


def flight_payload(html: str) -> str:
    """Reassemble the RSC payload from its self.__next_f.push() chunks.

    Parsed with raw_decode rather than a regex because the chunks are JSON
    string literals full of escaped quotes, and a regex that handles those
    correctly is a regex nobody should have to read.
    """
    parts: list[str] = []
    index = 0
    while True:
        index = html.find("self.__next_f.push(", index)
        if index < 0:
            break
        start = html.index("(", index) + 1
        try:
            chunk, _ = _decoder.raw_decode(html, start)
        except ValueError:
            index = start
            continue
        if isinstance(chunk, list) and len(chunk) > 1 and isinstance(chunk[1], str):
            parts.append(chunk[1])
        index = start
    return "".join(parts)


def find_objects(text: str, marker: str) -> Iterator[dict]:
    """Yield each JSON object whose body contains `marker`, by decoding from
    the nearest preceding brace."""
    seen_at: set[int] = set()
    for match in re.finditer(re.escape(marker), text):
        start = text.rfind("{", 0, match.start())
        # >= 0, not > 0: an object can legitimately begin at index 0. Against
        # the live page it never does — the block is buried in a 200 KB
        # payload — so this only ever failed on minimal input, which is
        # precisely what a test provides.
        while start >= 0:
            if start in seen_at:
                break
            try:
                obj, _ = _decoder.raw_decode(text, start)
            except ValueError:
                if start == 0:
                    break
                start = text.rfind("{", 0, start)
                continue
            seen_at.add(start)
            if isinstance(obj, dict):
                yield obj
            break


def walk_rows(node: Any) -> Iterator[dict]:
    """Every TableLineDateRecord anywhere beneath `node`.

    Recursive rather than positional so a CMS reshuffle of the nesting does
    not silently return zero rows.
    """
    if isinstance(node, dict):
        if node.get("__typename") == "TableLineDateRecord":
            yield node
        for value in node.values():
            yield from walk_rows(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk_rows(item)


def as_datetime(value: str | None, end_of_day: bool = False) -> datetime | None:
    if not value or not ISO_DATE.match(value):
        return None
    date = datetime.strptime(value, "%Y-%m-%d").date()
    moment = dtime(23, 59, 59) if end_of_day else dtime(0, 0)
    return datetime.combine(date, moment, tzinfo=UTC)


def clean_title(title: str) -> tuple[str, bool]:
    """Strip the asterisk the site uses to flag caveated rows, and say so."""
    caveated = title.strip().endswith("*")
    return title.strip().rstrip("*").strip(), caveated


def extract(html: str, observed_at: datetime) -> list[ExtractedStatement]:
    payload = flight_payload(html)
    if not payload:
        return []

    out: list[ExtractedStatement] = []
    seen: set[tuple[str, str, str]] = set()

    for block in find_objects(payload, '"_modelApiKey":"block_table"'):
        season = block.get("seasonType") or "unknown"

        for table in block.get("table") or []:
            if not isinstance(table, dict) or table.get("hide"):
                continue
            season_from = as_datetime(table.get("startDate"))
            season_to = as_datetime(table.get("endDate"), end_of_day=True)

            for row in walk_rows(table):
                if row.get("hide"):
                    continue
                title_raw = (row.get("title") or "").strip()
                if not title_raw:
                    continue
                title, caveated = clean_title(title_raw)

                opens = as_datetime(row.get("valueOne"))
                closes = as_datetime(row.get("valueTow"), end_of_day=True)
                if opens is None and closes is None:
                    continue  # a text row, not a date row

                subtitle = (row.get("subtitle") or "").strip()

                # subtitle is part of the identity, not decoration: two Balme
                # rows share a title and differ only here
                key = (season, title.lower(), subtitle.lower())
                if key in seen:
                    continue
                seen.add(key)
                altitude = ALTITUDE.search(subtitle)

                window = " – ".join(
                    filter(None, [row.get("valueOne"), row.get("valueTow")])
                )
                # A row can speak for more than one sector — see MULTI_TARGETS.
                # An unmapped row still emits once, mention-only, so the
                # resolver and then the review queue can see it.
                targets = resolve_slugs(title, subtitle) or [None]

                for target in targets:
                    out.append(
                        ExtractedStatement(
                            feature_mention=f"{title} {subtitle}".strip(),
                            feature_slug=target,
                            statement_type=StatementType.OPENING,
                            # A schedule is not an observation. It says what is
                            # planned, never what is true right now — and it must
                            # lose to the live feed, which it does on trust weight.
                            status=StatusValue.UNKNOWN,
                            severity=0,
                            observed_at=observed_at,
                            valid_from=opens or season_from,
                            valid_to=closes or season_to,
                            summary_en=(
                                f"{title}: scheduled {season} season {window}"
                                " (indicative, subject to change)"
                            ),
                            original_text=f"{title_raw} — {subtitle} — {window}",
                            original_language="fr",
                            payload={
                                "schedule": True,
                                "season": season,
                                "opens": row.get("valueOne"),
                                "closes": row.get("valueTow"),
                                "season_window": {
                                    "start": table.get("startDate"),
                                    "end": table.get("endDate"),
                                },
                                "subtitle": subtitle,
                                "altitude_m": int(altitude.group(1)) if altitude else None,
                                # Their asterisk. Reproduced, not laundered into
                                # certainty — the operator does not guarantee these.
                                "caveated": caveated,
                                "caveat": (
                                    "Dates are indicative and subject to change "
                                    "with operating and weather conditions."
                                ),
                            },
                            extraction_method=ExtractionMethod.RULE,
                            extraction_confidence=1.0,
                            context=f"{season} season calendar",
                        )
                    )
    return out


class MbnrOpeningsScraper(Scraper):
    slug = "mbnr-openings"

    def collect(
        self, session: Session, source: Source
    ) -> list[tuple[Document, list[ExtractedStatement]]]:
        response = fetch(URL)
        document, is_new = store_document(session, source, URL, response)
        if not is_new:
            return []
        return [(document, extract(response.text, datetime.now(UTC)))]


def _dump() -> int:
    response = fetch(URL)
    statements = extract(response.text, datetime.now(UTC))
    print(f"{len(statements)} scheduled seasons\n")
    for statement in sorted(
        statements, key=lambda s: (s.payload["season"], s.feature_mention)
    ):
        mapped = statement.feature_slug or "UNMAPPED"
        star = " *" if statement.payload["caveated"] else ""
        print(
            f"{statement.payload['season']:<8} {statement.feature_mention:<30}"
            f" {statement.payload['opens']} → {statement.payload['closes']}"
            f"  [{mapped}]{star}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(_dump())
