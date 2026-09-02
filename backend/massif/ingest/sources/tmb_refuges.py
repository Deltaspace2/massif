"""Tour du Mont-Blanc hut availability, from the TMB booking portal.

    python -m massif.ingest.sources.tmb_refuges     # dry run, no DB writes

WHY THIS SOURCE EXISTS. Thirty-five of our huts had no status from anything,
and fifteen of those are Italian — the side CLAUDE.md records as BLOCKED,
because the commune of Courmayeur does not resolve and the tourist office is
the wrong kind of publisher for a notice. This is not a notice source. It is
the huts' own booking calendar, and it crosses the border because the Tour du
Mont-Blanc does: the same portal carries French, Italian and Swiss refuges in
one structure, which is the only thing in reach that does.

Structured, not prose — CLAUDE.md rule 6. Every day is a `cal-cell` with a
state in its class list, so nothing here needs a model and nothing depends on
rendered text that changes with the reader's language.

WHAT A CELL MEANS, from the portal's own legend:

    cal-cell--dispo        "Disponible"            beds free, count shown
    cal-cell--last         "Dernières places"      beds free, count shown
    cal-cell--full         "Complet ou fermé"      FULL **OR** SHUT
    cal-cell--unavailable  "Non réservable en ligne (contacter le refuge)"
    cal-cell--empty        grid padding, no date at all
    cal-cell--past         before today; carries no availability

**`--full` CAN NEVER PRODUCE A CLOSURE.** The portal itself refuses to
distinguish "every bed is taken" from "the hut is shut for the season", and
publishing that as closed would invent a closure out of a busy weekend — the
exact shape of wrong answer this project is arranged against. It says nothing,
and saying nothing is a real outcome here.

So only `--dispo` and `--last` are believable. This started out importing
`hut_reservation.run_around`, on the reasoning that both sources are booking
calendars and should collapse days to seasons with one piece of code. That was
wrong, and the fixture caught it before it shipped: **this portal marks today
itself `--past`**, so the run containing today is empty for every hut on every
day, and the source would have emitted nothing, for ever, while looking
correct. The calendar is forward-looking — it sells tomorrow onward — so the
question it can answer is "is this hut selling beds soon", not "is it selling
one today".

Hence `SEASON_GAP_DAYS`, and it does two jobs. A busy hut is `--full` for
weeks at a time — Bertone is full on 641 of its 731 days and is plainly open
in September — so bookable days come scattered, and a strict contiguous run
would have produced one-day windows that expire the same afternoon. Days are
grouped into a season across gaps shorter than this, and the season only
speaks if it starts within the same distance of today.

WHICH HUT A PAGE IS ABOUT. The same two independent screens as ffcam-refuges,
because a name on its own has already sent a hut season to a 4808 m route:
resolve against huts only, then make the match prove itself against the
altitude the portal prints in its own header ("50 pers alt. 2000m"). Anything
that fails either screen queues as an unresolved mention.

AUTOMATION. The index at /fr/refuges lists every hut the portal carries, so a
hut added there is picked up without a config change — there is no curated
URL list to maintain, which is the difference between this and `hut-sites`.
robots.txt is `User-agent: *` with no Disallow, checked 2 Sep 2026.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime

from selectolax.parser import HTMLParser
from sqlalchemy.orm import Session

from massif.db import session_scope
from massif.enums import ExtractionMethod, StatementType, StatusValue
from massif.ingest.base import ExtractedStatement, Scraper, fetch, store_document
from massif.ingest.fr_dates import MONTHS, _norm
from massif.models import Document, Feature, Source

BASE = "https://www.montourdumontblanc.com"
INDEX = f"{BASE}/fr/refuges"

# A name has to reach this before the altitude is even consulted. Same floor as
# the shared resolver, restated here so a change there is a deliberate change
# here too.
NAME_FLOOR = 88.0

# The portal rounds and our own figures come from OSM and IGN, so they disagree
# by tens of metres routinely. Wide enough to survive that, far too narrow to
# let a different building through: the huts this could confuse are hundreds of
# metres apart in height.
ALTITUDE_TOLERANCE_M = 120

# Only these two mean "a bed can be booked on this day", which is the only
# thing on the page that amounts to "the hut is operating".
BOOKABLE = {"cal-cell--dispo", "cal-cell--last"}

# The one number in this file, doing two jobs, and both are about the same
# fact: an alpine hut's season ends for months, not for a fortnight.
#
#   - Bookable days closer together than this are one season. A hut sold out
#     for three weeks in August is not two seasons with a hole in it.
#   - A season starting further away than this is not a claim about now. If
#     the soonest bed is in June, the hut is shut and we say nothing.
#
# Four weeks. Wide enough that a full month of "complet" does not split a
# summer in half, narrow enough that next season cannot be read as this one.
SEASON_GAP_DAYS = 28

# "50 pers alt. 2000m" in the header block. The altitude is the half we use as
# a screen; the capacity is carried for the report so a person can sanity-check
# a match without opening the page.
_HEADER = re.compile(r"(\d{1,4})\s*pers.*?alt\.\s*(\d{3,4})\s*m", re.IGNORECASE | re.DOTALL)


def _month_start(title: str) -> date | None:
    """"Septembre2026" -> 1 Sep 2026.

    Through `_norm`, so the accented months are folded before the lookup —
    "Décembre" and "Août" do not match a bare literal, and that is the house
    speciality of a bug here (CLAUDE.md rule 1, and four separate incidents).
    """
    flat = _norm(title)
    match = re.search(r"([a-z]+)\s*(\d{4})", flat)
    if match is None:
        return None
    month = MONTHS.get(match.group(1))
    if month is None:
        return None
    return date(int(match.group(2)), month, 1)


def bookable_days(tree: HTMLParser) -> list[tuple[date, str]]:
    """Every day the portal will actually sell a bed on, as (date, "open").

    Returned in the shape `run_around` wants — the same shape the CAS source
    builds — so the two booking calendars are collapsed into seasons by one
    piece of code rather than two that agree until they do not.
    """
    out: list[tuple[date, str]] = []
    for block in tree.css(".cal-month"):
        title = block.css_first(".cal-month__title")
        first = _month_start(title.text(strip=True)) if title else None
        if first is None:
            continue
        for cell in block.css(".cal-cell"):
            classes = set((cell.attributes.get("class") or "").split())
            if not (classes & BOOKABLE):
                continue
            number = cell.css_first(".cal-cell__num")
            if number is None:
                continue
            try:
                day = int(number.text(strip=True))
                out.append((first.replace(day=day), "open"))
            except ValueError:
                # A padding cell, or a month grid we have misread. Either way
                # it is not a day, and inventing one is how a season grows a
                # week it was never sold.
                continue
    out.sort()
    return out


def hut_header(tree: HTMLParser) -> tuple[str | None, int | None, int | None]:
    """(name, capacity, altitude) as the portal prints them."""
    heading = tree.css_first("h1")
    name = heading.text(strip=True) if heading else None
    # strip=True, not the default: with whitespace kept, this page's header
    # sits 4169 characters in behind the template's indentation, and any window
    # small enough to be safe misses it. Stripped, the same header is at 195.
    body = tree.body.text(strip=True) if tree.body else ""
    found = _HEADER.search(body[:4000])
    if found is None:
        return name, None, None
    return name, int(found.group(1)), int(found.group(2))


def season_from(days: list[date], on: date) -> tuple[date, date] | None:
    """The selling season `on` falls in or is about to, or None.

    Days are grouped into seasons across gaps shorter than `SEASON_GAP_DAYS`,
    and the first season whose end is not already past is the candidate. It
    only speaks if its first day is within the same distance of `on`: a hut
    whose soonest bed is in June is shut now, and saying "open" because a
    calendar exists would be this site inventing a season out of a booking
    engine.

    The window starts at `on`, never at the first bookable day. The portal
    marks today `--past` and sells from tomorrow, so the first bookable day is
    always in the future — anchoring there would publish a status that is not
    in force yet and leave the hut unknown on the day someone is reading.
    """
    if not days:
        return None
    seasons: list[list[date]] = [[days[0]]]
    for day in days[1:]:
        if (day - seasons[-1][-1]).days > SEASON_GAP_DAYS:
            seasons.append([day])
        else:
            seasons[-1].append(day)
    for season in seasons:
        if season[-1] < on:
            continue  # already over
        if (season[0] - on).days > SEASON_GAP_DAYS:
            return None  # the next one is too far off to be about now
        return on, season[-1]
    return None


def extract(html: str, observed_at: datetime) -> list[ExtractedStatement]:
    """One statement at most: that this hut is selling beds, and until when.

    A calendar of 731 days is a handful of seasons, not 731 claims. If nothing
    is bookable near the observation date there is nothing to say — the hut may
    be full, it may be shut, and the portal does not distinguish. It stays
    unknown, which is the honest answer.
    """
    tree = HTMLParser(html)
    name, capacity, altitude = hut_header(tree)
    if not name:
        return []
    days = [day for day, _ in bookable_days(tree)]
    window = season_from(days, observed_at.date())
    if window is None:
        return []
    start, end = window
    sold = [d for d in days if start <= d <= end]
    return [
        ExtractedStatement(
            feature_mention=name,
            statement_type=StatementType.OPENING,
            status=StatusValue.OPEN,
            severity=0,
            observed_at=observed_at,
            valid_from=datetime(start.year, start.month, start.day, tzinfo=UTC),
            valid_to=datetime(end.year, end.month, end.day, 23, 59, 59, tzinfo=UTC),
            summary_en=(
                f"Selling beds on the Tour du Mont-Blanc booking portal for "
                f"{len(sold)} date{'' if len(sold) == 1 else 's'} up to "
                f"{end:%d %b %Y}, so the hut is operating. Dates the portal "
                f"shows as taken may be full or shut — it does not say which, "
                f"so they are not read as a closure"
            ),
            original_text=f"{name} — calendrier des disponibilit\u00e9s",
            original_language="fr",
            extraction_method=ExtractionMethod.RULE,
            payload={
                # Availability, not a wardening season: the portal sells beds
                # and says nothing about who is running the building.
                "bookable": True,
                "bookable_days": len(sold),
                "altitude_m": altitude,
                "capacity": capacity,
                "tmb_name": name,
            },
        )
    ]


def _hut_urls(index_html: str) -> list[str]:
    """Every hut page the index links to. One level deep, deduplicated."""
    seen: dict[str, None] = {}
    for link in HTMLParser(index_html).css("a[href]"):
        href = (link.attributes.get("href") or "").strip()
        if href.startswith("/fr/refuges/") and href.count("/") == 3:
            seen.setdefault(f"{BASE}{href}", None)
    return list(seen)


class TmbRefugesScraper(Scraper):
    slug = "tmb-refuges"

    def __init__(self) -> None:
        self._huts = None

    def collect(
        self, session: Session, source: Source
    ) -> list[tuple[Document, list[ExtractedStatement]]]:
        index = fetch(INDEX)
        document, _ = store_document(session, source, INDEX, index)
        # Stored for provenance: it is the page that decides which huts this
        # source covers at all. It carries no calendar, so it extracts to
        # nothing, which is correct rather than a miss.
        out: list[tuple[Document, list[ExtractedStatement]]] = [(document, [])]

        urls = _hut_urls(index.text)
        print(f"{len(urls)} hut pages on the TMB portal")
        for url in urls:
            try:
                page = fetch(url)
            except Exception as error:  # noqa: BLE001 — one dead page is not a run
                print(f"  ! {url}: {type(error).__name__}: {error}")
                continue
            stored, _ = store_document(session, source, url, page)
            out.append((stored, extract(page.text, stored.fetched_at)))
        return out

    def extract_stored(self, document: Document) -> list[ExtractedStatement]:
        raw = document.raw_text or (document.raw_content or b"").decode("utf-8", "replace")
        return extract(raw, document.published_at or document.fetched_at)

    def resolve_and_build(self, session, source, document, item, resolver):
        """Huts only, then prove the name against the altitude.

        Two independent screens, the same pair ffcam-refuges uses and for the
        same reason: this portal carries valley gîtes and hotels whose names
        are close to huts we do carry, and a name score cannot tell you which
        building it found. Every exit that is not a confirmed hut queues and
        returns None rather than falling through to the shared index.
        """
        from massif.ingest.sources.ffcam import HutResolver

        altitude = (item.payload or {}).get("altitude_m")
        if self._huts is None:
            self._huts = HutResolver(session)
        match, candidates = self._huts.resolve(item.feature_mention)

        def refuse(why: str) -> None:
            resolver.queue_unresolved(
                item.feature_mention,
                candidates,
                source_id=source.id,
                document_id=document.id,
                context=why,
            )
            return None

        if match is None or match.score < NAME_FLOOR:
            return refuse(
                f"no hut reached {NAME_FLOOR:.0f} for this name; "
                f"the portal publishes it at {altitude} m"
            )
        feature = session.get(Feature, match.feature_id)
        if feature is None:
            return refuse("matched a feature that is no longer in the table")

        ours = feature.alt_max or feature.alt_min
        if altitude is None or ours is None:
            missing = "the portal" if altitude is None else f"our {feature.slug}"
            return refuse(
                f"name matched {feature.slug} at {match.score:.0f} but "
                f"{missing} carries no altitude to check it against"
            )
        if abs(int(ours) - int(altitude)) > ALTITUDE_TOLERANCE_M:
            return refuse(
                f"name matched {feature.slug} at {match.score:.0f} but the portal "
                f"publishes {altitude} m against our {int(ours)} m"
            )

        item.feature_slug = feature.slug
        return super().resolve_and_build(session, source, document, item, resolver)


def _dump() -> int:
    """What the parser makes of the live portal, writing nothing."""
    index = fetch(INDEX)
    urls = _hut_urls(index.text)
    now = datetime.now(UTC)
    print(f"{len(urls)} hut pages on the TMB portal\n")
    speaking = 0
    for url in sorted(urls):
        try:
            page = fetch(url)
        except Exception as error:  # noqa: BLE001
            print(f"  ! {url}: {type(error).__name__}: {error}")
            continue
        tree = HTMLParser(page.text)
        name, capacity, altitude = hut_header(tree)
        days = bookable_days(tree)
        found = extract(page.text, now)
        if found:
            speaking += 1
            statement = found[0]
            window = f"{statement.valid_from:%d %b} – {statement.valid_to:%d %b %Y}"
        else:
            window = f"nothing bookable on {now:%d %b}"
        print(
            f"  {(name or url)[:34]:36} {str(altitude or '?'):>5}m "
            f"{str(capacity or '?'):>4}p  {len(days):>3} bookable days  {window}"
        )
    print(f"\n{speaking} of {len(urls)} huts are bookable today and would speak")
    return 0


if __name__ == "__main__":
    with session_scope():
        raise SystemExit(_dump())
