"""Mont-Blanc Natural Resort — live lift status.

https://www.montblancnaturalresort.com/fr/infos-live

Not compagniedumontblanc.fr: that is the corporate site and carries no
operational data. Same operator, different property.

DOM, established by recon rather than guesswork:

    div.o_InfoLiveTab[id]                   stable sector id, e.g. "brevent"
      div.o_InfoLiveTab_label               "Brévent - 2525 m"
      div.o_BlockOpening
        div.o_BlockOpening_tabs             "Remontées ( 0 / 3 ) Restaurants ( 0 / 2 )"
        div.m_PIOItem
          div.m_PIOItem_timeList
            div.m_PIOItem_time              "07:20 - 16:10"   (repeats)
          div.m_PIOItem_name                "TPH AIGUILLE DU MIDI"
          div.m_PIOItem_message             "Fermé de 13h00 et 14h00"
          div.m_PIOItem_status
            i.a_IconStatusPoi-<state>       the actual status

Two things this gets right that the first version did not:

1. Status comes from the icon modifier class, not from text. m_PIOItem_status
   has no text content at all, so any text-based reading of it was guesswork.

2. "pending" is not "closed". Before the first lift of the day every item is
   pending and every sector reads 0/N. Publishing that as CLOSED would have the
   map declaring Chamonix shut every morning until 07:20.

The site is a Lumiplan/eLiberty white-label, so this parser is likely to port
to other French resorts with little more than a new sector map.
"""

from __future__ import annotations

import re
import sys
from datetime import UTC, datetime
from datetime import time as dtime
from zoneinfo import ZoneInfo

from selectolax.parser import HTMLParser, Node
from sqlalchemy.orm import Session

from massif.enums import ExtractionMethod, StatementType, StatusValue
from massif.ingest.base import ExtractedStatement, Scraper, fetch, store_document
from massif.models import Document, Source

URL = "https://www.montblancnaturalresort.com/fr/infos-live"

# Stable tab id -> our feature slug. Exact mapping, no fuzzy matching: the
# source tells us what each sector is, so we should not be guessing.
SECTOR_FEATURES: dict[str, str] = {
    "aiguille-du-midi": "aiguille-du-midi",
    "montenvers-mer-de-glace": "montenvers-railway",
    "brevent": "brevent",
    "flegere": "flegere",
    "balme": "balme-le-tour",
    "grands-montets": "grands-montets",
    "houches-saint-gervais": "les-houches",
    "les-planards": "les-planards",
    "megeve-rochebrune": "megeve-rochebrune",
    "les-bossons": "telesiege-des-bossons",
    "megeve-mont-arbois": "megeve-mont-arbois",
}

# Icon modifier -> status. Only "pending" has been observed live; the others
# are inferred from the naming scheme and will be confirmed in season. An
# unrecognised modifier is recorded verbatim rather than guessed at.
STATUS_ICONS: dict[str, tuple[StatusValue, int]] = {
    "open": (StatusValue.OPEN, 0),
    "opened": (StatusValue.OPEN, 0),
    "pending": (StatusValue.UNKNOWN, 0),
    "closed": (StatusValue.CLOSED, 1),
    "close": (StatusValue.CLOSED, 1),
    "disrupted": (StatusValue.RESTRICTED, 2),
    "hold": (StatusValue.RESTRICTED, 2),
}

ICON_CLASS = re.compile(r"a_IconStatusPoi-([a-zA-Z]+)")
COUNT = re.compile(r"([A-Za-zÀ-ÿ&\s]+?)\s*\(\s*(\d+)\s*/\s*(\d+)\s*\)")
ALTITUDE = re.compile(r"-\s*(\d{3,4})\s*m\s*$")
TIME_RANGE = re.compile(r"(\d{1,2}):(\d{2})\s*[-–—]\s*(\d{1,2}):(\d{2})")

# The mountain keeps its own clock, not the reader's. Steven checking from
# Manila at 03:00 is looking at Chamonix at 21:00.
RESORT_TZ = ZoneInfo("Europe/Paris")

# Categories that mean "uphill transport" rather than restaurants or ticket
# desks. Montenvers is a rack railway, hence the second entry.
LIFT_CATEGORIES = ("remontees", "trains visites", "trains & visites")


def _text(node: Node | None) -> str:
    if node is None:
        return ""
    return " ".join(node.text(separator=" ", strip=True).split())


def icon_status(item: Node) -> tuple[StatusValue, int, str | None]:
    """Read the status icon. Returns (status, severity, raw_modifier)."""
    status_node = item.css_first("div.m_PIOItem_status i")
    if status_node is None:
        return StatusValue.UNKNOWN, 0, None
    classes = status_node.attributes.get("class") or ""
    match = ICON_CLASS.search(classes)
    if match is None:
        return StatusValue.UNKNOWN, 0, None
    raw = match.group(1).lower()
    status, severity = STATUS_ICONS.get(raw, (StatusValue.UNKNOWN, 0))
    return status, severity, raw


def parse_counts(text: str) -> dict[str, dict[str, int]]:
    """'Remontées ( 0 / 4 ) Restaurants ( 0 / 2 )' -> structured counts."""
    out: dict[str, dict[str, int]] = {}
    for label, open_n, total_n in COUNT.findall(text):
        key = " ".join(label.split()).lower()
        out[key] = {"open": int(open_n), "total": int(total_n)}
    return out


def lift_counts(counts: dict[str, dict[str, int]]) -> dict[str, int] | None:
    for key, value in counts.items():
        normalised = key.replace("é", "e").replace("&", "").strip()
        normalised = " ".join(normalised.split())
        if any(normalised.startswith(c.replace("&", "").strip())
               for c in LIFT_CATEGORIES):
            return value
    return None


def parse_item(item: Node) -> dict:
    times = [_text(t) for t in item.css("div.m_PIOItem_time")]
    status, severity, raw = icon_status(item)
    return {
        "name": _text(item.css_first("div.m_PIOItem_name")),
        "times": [t for t in times if t],
        "message": _text(item.css_first("div.m_PIOItem_message")),
        "status": status,
        "severity": severity,
        "raw_status": raw,
        "is_trail": "m_PIOItem-trail" in (item.attributes.get("class") or ""),
    }


def day_window(times: list[str]) -> tuple[dtime, dtime] | None:
    """First opening and last closing across a lift's time ranges."""
    bounds: list[tuple[dtime, dtime]] = []
    for text in times:
        match = TIME_RANGE.search(text)
        if match:
            o_h, o_m, c_h, c_m = (int(g) for g in match.groups())
            bounds.append((dtime(o_h % 24, o_m), dtime(c_h % 24, c_m)))
    if not bounds:
        return None
    return min(b[0] for b in bounds), max(b[1] for b in bounds)


def pending_phase(items: list[dict], now: datetime) -> str:
    """Word a pending sector by where the resort clock actually is.

    "Not yet running today" is true at 06:00 and false at 21:00, and the
    difference is invisible to anyone reading from another timezone.
    """
    local = now.astimezone(RESORT_TZ)
    windows = [w for w in (day_window(i["times"]) for i in items) if w]
    if not windows:
        return "not currently running"

    first_open = min(w[0] for w in windows)
    last_close = max(w[1] for w in windows)
    clock = local.time()

    # Both ends of the day, not just the reopening. "Reopens 08:20" tells you
    # when to turn up and nothing about how long you have — and the last lift
    # down is the number that decides whether a day out is feasible at all.
    window = f"{first_open.strftime('%H:%M')}–{last_close.strftime('%H:%M')}"

    if clock < first_open:
        return f"closed now · runs {window} today"
    if clock > last_close:
        return f"closed for the day · runs {window}"
    return f"not running despite operating hours {window}"


def sector_status(
    items: list[dict],
    counts: dict[str, int] | None,
    now: datetime | None = None,
) -> tuple[StatusValue, int, str]:
    """Derive a sector status that does not lie about why it is shut.

    A sector showing 0/N is only genuinely closed if none of its lifts are
    merely waiting to start. Closed-because-it-is-night is not news;
    closed-because-of-rockfall is, and the two must never read alike.
    """
    now = now or datetime.now(UTC)
    lifts = [i for i in items if not i["is_trail"]]
    if lifts and all(i["raw_status"] == "pending" for i in lifts):
        return StatusValue.UNKNOWN, 0, pending_phase(lifts, now)

    if counts is None:
        return StatusValue.UNKNOWN, 0, "no lift counts published"

    open_n, total_n = counts["open"], counts["total"]
    if total_n == 0:
        return StatusValue.UNKNOWN, 0, "no lifts listed"
    plural = "lift" if total_n == 1 else "lifts"
    if open_n == 0:
        return (
            StatusValue.CLOSED,
            1,
            f"its only {plural} is closed" if total_n == 1
            else f"all {total_n} {plural} closed",
        )
    if open_n == total_n:
        return (
            StatusValue.OPEN,
            0,
            f"its only {plural} is open" if total_n == 1
            else f"all {total_n} {plural} open",
        )
    return StatusValue.RESTRICTED, 1, f"{open_n} of {total_n} lifts open"


def extract(tree: HTMLParser, observed_at: datetime) -> list[ExtractedStatement]:
    out: list[ExtractedStatement] = []
    unknown_modifiers: set[str] = set()

    for tab in tree.css("div.o_InfoLiveTab"):
        tab_id = tab.attributes.get("id")
        if not tab_id:
            continue

        label = _text(tab.css_first("div.o_InfoLiveTab_label"))
        block = tab.css_first("div.o_BlockOpening")
        if block is None:
            continue

        counts = parse_counts(_text(block.css_first("div.o_BlockOpening_tabs")))
        items = [parse_item(i) for i in block.css("div.m_PIOItem")]

        for item in items:
            if item["raw_status"] and item["raw_status"] not in STATUS_ICONS:
                unknown_modifiers.add(item["raw_status"])

        # ---- sector-level statement, exact identity via the tab id
        slug = SECTOR_FEATURES.get(tab_id)
        status, severity, note = sector_status(
            items, lift_counts(counts), observed_at
        )
        scheduled = status is StatusValue.UNKNOWN and bool(
            [i for i in items if not i['is_trail']]
        )
        altitude = ALTITUDE.search(label)

        out.append(
            ExtractedStatement(
                feature_mention=label or tab_id,
                feature_slug=slug,
                statement_type=StatementType.OPERATIONAL_STATUS,
                status=status,
                severity=severity,
                observed_at=observed_at,
                summary_en=f"{label or tab_id}: {note}",
                original_text=_text(block)[:2000],
                original_language="fr",
                payload={
                    "tab_id": tab_id,
                    # outside_hours is routine and must never be presented
                    # like an unplanned closure
                    "closure_kind": "outside_hours" if scheduled else None,
                    "counts": counts,
                    "altitude_m": int(altitude.group(1)) if altitude else None,
                    "lifts": [
                        {
                            "name": i["name"],
                            "status": i["status"].value,
                            "raw_status": i["raw_status"],
                            "times": i["times"],
                            "message": i["message"],
                        }
                        for i in items
                        if not i["is_trail"]
                    ],
                },
                extraction_method=ExtractionMethod.RULE,
                extraction_confidence=1.0 if slug else 0.5,
                context=f"tab id {tab_id}",
            )
        )

        # ---- per-machine statements. These resolve by name, so unknown lifts
        # land in the review queue and become the alias work list.
        for item in items:
            if item["is_trail"] or not item["name"] or not slug:
                continue
            out.append(
                ExtractedStatement(
                    feature_mention=item["name"],
                    # scoped to this sector: a lift can only ever resolve to a
                    # lift of the sector that published it
                    parent_slug=slug,
                    statement_type=StatementType.OPERATIONAL_STATUS,
                    status=item["status"],
                    severity=item["severity"],
                    observed_at=observed_at,
                    summary_en=(
                        f"{item['name']}: {item['raw_status'] or 'unknown'}"
                        + (f" — {item['message']}" if item["message"] else "")
                    ),
                    original_text=" | ".join(
                        filter(None, [*item["times"], item["name"], item["message"]])
                    ),
                    original_language="fr",
                    payload={
                        "sector": tab_id,
                        "times": item["times"],
                        "message": item["message"],
                        "raw_status": item["raw_status"],
                    },
                    extraction_method=ExtractionMethod.RULE,
                    extraction_confidence=0.95,
                    context=f"lift in sector {tab_id}",
                )
            )

    if unknown_modifiers:
        print(
            f"  note: unrecognised status icons {sorted(unknown_modifiers)} — "
            f"add them to STATUS_ICONS",
            file=sys.stderr,
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
            return []  # unchanged since last fetch
        tree = HTMLParser(response.text)
        return [(document, extract(tree, datetime.now(UTC)))]


def _dump() -> int:
    """Show what the parser makes of the live page, without touching the DB."""
    response = fetch(URL)
    tree = HTMLParser(response.text)
    statements = extract(tree, datetime.now(UTC))

    sectors = [s for s in statements if s.payload.get("tab_id")]
    machines = [s for s in statements if s.payload.get("sector")]

    print(f"{len(sectors)} sectors, {len(machines)} lifts\n")
    for statement in sectors:
        mapped = "->" + (statement.feature_slug or "UNMAPPED")
        print(f"{statement.payload['tab_id']:<26} {statement.status.value:<10} {mapped}")
        print(f"    {statement.summary_en}")
        print(f"    counts: {statement.payload['counts']}")
        for lift in statement.payload["lifts"]:
            note = f"  [{lift['message']}]" if lift["message"] else ""
            print(f"      {lift['name']:<28} {lift['raw_status'] or '?':<9} "
                  f"{', '.join(lift['times'])}{note}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(_dump())
