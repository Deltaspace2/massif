"""FFCAM refuge warden seasons — the dated window a hut is open to the public.

    python -m massif.ingest.sources.ffcam        # dry run, no DB

WHY THIS SOURCE. Every hut on the site read "unknown" because nothing we
ingested made a *dated* claim that a hut is open or shut. refuges.info says a
handful are shut and says nothing at all about the rest; camptocamp describes
buildings, not seasons. FFCAM owns and runs fifteen of the huts inside this
massif — Goûter, Tête Rousse, Grands Mulets, Couvercle, Argentière, Albert 1er,
Conscrits, Durier, Leschaux, Envers, Vallot — and publishes, per hut, the
"Période de gardiennage": the days it is open to the public, with a year.

WHY THIS IS `OPEN` AND `mbnr-openings` IS `UNKNOWN`. That scraper deliberately
emits UNKNOWN because a lift's published calendar is a *plan* that is contested
by a live feed from the same operator: the schedule says the Aiguille du Midi
runs today, the live feed says it is held for wind, and the plan must lose. No
such feed exists for huts, and this is not a plan — it is the operator of the
building stating the dates it is open to the public, and taking bookings
against them. Inside that window the operator is saying the hut is open, so
that is what we record.

It is still only ever the *warden* season, which is why nothing is emitted
outside the window. Most of these huts have a winter room — FFCAM's own pages
advertise "Hors gardiennage: 30 couchages" and sell bookings for it — so
"unwardened" is emphatically not "closed", and synthesising a closure from the
end of the season would invent a shut hut out of an unstaffed one.

TRUST. Seeded below mairie-saint-gervais (1.00) on purpose. Saint-Gervais shut
the Goûter and Tête Rousse by arrêté on 11 August over rockfall, in the middle
of the very season this source publishes. A season must never outrank a decree,
and at 0.90 it does not.

SHAPE OF THE PAGES. Two, and both are in the fixtures:

  * montblanc.ffcam.fr is one portal for three huts — repeated
    `div.block-refuge` (heading, altitude, `div.periode`).
  * every other refuge has its own site, where the single `div.ouverture`
    carries the same text and the `h1` names the hut.

Both are self-describing: name and altitude live on the same page as the dates,
so a stored document re-extracts on its own with no directory lookup. That is
deliberate — the directory page is where we learn which huts are in the massif,
and if the coordinates only reached the resolver through `collect()` then
`reextract` could never resolve anything.

WHAT IS NOT PARSED, AND WHY IT MUST STAY THAT WAY. Refuge du Couvercle's season
reads "De début avril à fin septembre" — no days, no year. It emits nothing.
An undated notice must never claim a present-tense status (CLAUDE.md rule 3),
and "early April" is not a date. The guard is an explicit four-digit year.
"""

from __future__ import annotations

import calendar
import re
from datetime import UTC, datetime

from selectolax.parser import HTMLParser
from sqlalchemy import select
from sqlalchemy.orm import Session

from massif.enums import ExtractionMethod, FeatureType, StatementType, StatusValue
from massif.ingest.base import ExtractedStatement, Scraper, fetch, store_document
from massif.ingest.fr_dates import MONTHS, DateRange, parse_range, strip_accents
from massif.ingest.resolve import FeatureResolver
from massif.models import Document, Feature, Source

DIRECTORY = "https://www.ffcam.fr/rechercher_refuge_chalet.html"

# A name has to clear this AND the altitude check below. Both, never either:
# a score alone cannot tell you which mountain something is on (CLAUDE.md 8).
NAME_FLOOR = 88.0
ALTITUDE_TOLERANCE_M = 200

ALTITUDE = re.compile(r"\b(\d{3,4})\s*m\b")
# "REFUGE DU COUVERCLE (FFCAM)" -> "REFUGE DU COUVERCLE"
OPERATOR_SUFFIX = re.compile(r"\s*\((?:FFCAM|CAF)\)\s*$", re.I)

# Huts FFCAM lists that we deliberately take no season from. Recorded with the
# reason so the next person does not "fix" the gap by deleting the guard.
EXCLUDED: dict[str, str] = {
    # Its own block on the portal says so: "La FFCAM n'est plus gestionnaire du
    # refuge du Nid d'Aigle." They are not the authority on its season any
    # more, so silence is the honest answer rather than a stale window.
    "refuge du nid d'aigle": "FFCAM's page states it no longer manages this refuge",
    # The seasonal base camp beside Tête Rousse, listed as its own directory row
    # (3167 m, 40 places) two metres from the refuge (3165 m, 72 places). No
    # altitude check on earth separates those two, and it is not a hut in our
    # directory — it is an annexe of one that is. Letting it resolve would put
    # a second row in the fight for Tête Rousse's single status slot.
    "tete rousse- camp de base": "base-camp annexe of Refuge de Tête Rousse, not a separate hut",
}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", strip_accents(text).lower()).strip()


def _clean_name(raw: str) -> str:
    return OPERATOR_SUFFIX.sub("", " ".join(raw.split())).strip()


def _altitude_near(node) -> int | None:
    """The altitude published beside this block.

    Walks outward from the season block rather than scanning the page, because
    a refuge site can mention a summit's height in prose and the first number
    on the page is not necessarily the building's. Failing to find one is safe:
    the resolver refuses a match it cannot check against altitude.
    """
    current = node
    for _ in range(5):
        if current is None:
            return None
        found = ALTITUDE.search(current.text(separator=" "))
        if found:
            return int(found.group(1))
        current = current.parent
    return None


# A season written in words rather than dates: "De début avril à fin
# septembre". Four of the fifteen FFCAM huts publish only this, and skipping
# them left Argentière, Couvercle, Leschaux and Durier with no status at all
# while their own operator was saying when they are wardened.
#
# Read CONSERVATIVELY, and that is the whole safety of it. Each end of the
# phrase is a range of days, and we take the narrowest window the words can
# mean — the LAST day a start could be, the FIRST day an end could be. "Début
# avril to fin septembre" becomes 10 Apr – 21 Sep, never 1 Apr – 30 Sep. The
# statement is therefore always a subset of what the source said: we may say
# nothing on a day the hut is in fact wardened, and can never say it is
# wardened on a day the words do not cover.
QUALIFIERS = {"debut": (1, 10), "mi": (11, 20), "fin": (21, 31)}
COARSE_END = re.compile(
    r"(?:(\d{1,2})\s+)?(?:(debut|mi|fin)\s*-?\s*)?(" + "|".join(MONTHS) + r")\b(?:\s+(\d{4}))?"
)


def _last_day(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def _coarse_windows(line: str, year: int) -> DateRange | None:
    """A worded season narrowed to the days it certainly covers.

    Each end may be worded ("début juin") or exact ("24 août 2026"), in any
    mix — Refuge Durier publishes "De début juin au 24 août 2026", one of each.
    An end that is neither is not an end, and a phrase without two of them gets
    the same silence as no phrase at all.
    """
    found = COARSE_END.findall(_norm(line))
    if len(found) != 2:
        return None

    ends = []
    for index, (day, word, month, explicit_year) in enumerate(found):
        if not day and not word:
            return None  # a bare month name is not a date
        month_number = MONTHS[month]
        on = int(explicit_year) if explicit_year else year
        # Latest a start could be; earliest an end could be. The window is
        # always a subset of what the words allow, never a superset.
        number = int(day) if day else QUALIFIERS[word][1 if index == 0 else 0]
        number = min(number, _last_day(on, month_number))
        ends.append((on, month_number, number))

    (y1, m1, d1), (y2, m2, d2) = ends
    start = datetime(y1, m1, d1, tzinfo=UTC)
    end = datetime(y2, m2, d2, 23, 59, 59, tzinfo=UTC)
    if start >= end:
        return None
    return DateRange(start, end, "ffcam_coarse")


def _windows(text: str, year: int | None = None) -> list[tuple[str, DateRange]]:
    """The dated season(s) in one "Période de gardiennage" block.

    Two shapes, both real:
      "Ouverture du refuge au public le 30 mai 2026" +
      "Fermeture du refuge au public le 4 octobre 2026 à 7h"   -> one window
      "Printemps : 14 mars au 3 mai 2026"                      -> one window
      "Été : 23 mai au 13 septembre 2026"                      -> another

    A hut with a spring and a summer season gets two statements, not one span
    covering the gap between them: `retire_replaced` keeps them apart on the
    overlap test, exactly as it does for mbnr-openings' two seasons.

    `fr_dates.parse_range` decides whether a phrase carries DATES, and a local
    "must contain a four-digit year" screen in front of it was tried and
    removed: it rejected nothing parse_range does not already reject, and its
    only real effect was to silently drop the `30/05/26` form.

    A phrase it refuses gets one more reading, by `_coarse_windows`, as a
    season written in words. That is not a loosening of rule 3 — an undated
    notice still says nothing — it is reading a season that IS bounded, just
    bounded in words, and narrowing it to the days those words certainly
    cover.
    """
    year = year or datetime.now(UTC).year
    opened: datetime | None = None
    closed: datetime | None = None
    out: list[tuple[str, DateRange]] = []

    for line in (line.strip() for line in text.splitlines()):
        if not line:
            continue
        low = _norm(line)
        # Only when the line is nothing BUT the heading. Leschaux repeats it
        # inline — "Période de gardiennage : De mi juin a mi septembre" — and
        # skipping on a prefix match threw that hut's only season away.
        if low.rstrip(" :.-") == "periode de gardiennage":
            continue
        if low.startswith("ouverture"):
            found = parse_range(line)
            if found and found.start:
                opened = found.start
            continue
        if low.startswith("fermeture"):
            found = parse_range(line)
            if found and found.end:
                closed = found.end
            continue

        label, separator, rest = line.partition(":")
        if not separator:
            label, rest = "", line
        rest = rest.strip()
        # fr_dates wants "du X au Y"; FFCAM writes "Printemps : X au Y".
        if not _norm(rest).startswith("du "):
            rest = f"du {rest}"
        found = parse_range(rest)
        if found and found.start and found.end and found.start < found.end:
            out.append((_clean_name(label) or "Gardiennage", found))
            continue
        coarse = _coarse_windows(rest, year)
        if coarse is not None:
            named = _clean_name(label)
            # Leschaux repeats the heading as its own label; that is not a
            # season name.
            if _norm(named) == "periode de gardiennage":
                named = ""
            out.append((named or "Gardiennage", coarse))

    if opened and closed and opened < closed:
        out.append(("Gardiennage", DateRange(opened, closed, "ffcam_open_close")))
    return out


def _season_blocks(tree: HTMLParser) -> list[tuple[str, int | None, str]]:
    """(name, altitude, season text) for every hut described by one page."""
    blocks = tree.css("div.block-refuge")
    if blocks:
        out = []
        for block in blocks:
            heading = block.css_first("h1,h2,h3,h4")
            period = block.css_first("div.periode")
            if heading is None or period is None:
                continue
            out.append(
                (
                    _clean_name(heading.text(strip=True)),
                    _altitude_near(block),
                    period.text(separator="\n"),
                )
            )
        return out

    heading = tree.css_first("h1")
    period = tree.css_first("div.ouverture")
    if heading is None or period is None:
        return []
    return [
        (
            _clean_name(heading.text(strip=True)),
            _altitude_near(period),
            period.text(separator="\n"),
        )
    ]


def _english(moment: datetime) -> str:
    return f"{moment.day} {moment:%b} {moment.year}"


def extract(html: str, observed_at: datetime) -> list[ExtractedStatement]:
    tree = HTMLParser(html)
    out: list[ExtractedStatement] = []

    for name, altitude, text in _season_blocks(tree):
        if _norm(name) in EXCLUDED:
            continue
        for label, window in _windows(text, observed_at.year):
            out.append(
                ExtractedStatement(
                    feature_mention=name,
                    statement_type=StatementType.OPENING,
                    status=StatusValue.OPEN,
                    severity=0,
                    observed_at=observed_at,
                    valid_from=window.start,
                    valid_to=window.end,
                    summary_en=(
                        f"Wardened roughly {_english(window.start)} – "
                        f"{_english(window.end)} — the operator publishes this "
                        f"season in words, not dates, so these are the days "
                        f"those words certainly cover"
                        if window.rule == "ffcam_coarse"
                        else f"Wardened and open to the public "
                        f"{_english(window.start)} – {_english(window.end)}"
                    ),
                    original_text=" ".join(text.split()),
                    original_language="fr",
                    extraction_method=ExtractionMethod.RULE,
                    payload={
                        # Says the warden is there, NOT that the hut is shut the
                        # rest of the year. Most of these have a winter room.
                        "wardened": True,
                        # Our narrowing of a season the operator wrote in
                        # words. The dates are ours, not theirs, and nothing
                        # may present them as though they were published.
                        "approximate": window.rule == "ffcam_coarse",
                        "season": label,
                        "altitude_m": altitude,
                        "ffcam_name": name,
                    },
                )
            )
    return out


class HutResolver(FeatureResolver):
    """A FeatureResolver that can only ever return a hut.

    `normalise` strips the generic nouns — "refuge", "du" — so "REFUGE DU
    GOÛTER" and the Goûter Route's own alias "Goûter" reduce to the same key,
    and the route was indexed first. The shared resolver therefore matched this
    source's hut season to a 4808 m mountaineering route at a score of 100.

    CLAUDE.md already names the fix for this shape of bug: scope the
    resolution. It is what `parent_slug` does for an operator's own lifts, and
    the reason it exists is "TC MER DE GLACE" resolving to the Mer de Glace
    glacier. FFCAM publishes a directory of refuges and nothing else, so a
    season it prints belongs to a hut or to nothing.
    """

    def reload(self) -> None:
        super().reload()
        huts = {
            str(feature_id)
            for feature_id in self.session.scalars(
                select(Feature.id).where(Feature.feature_type == FeatureType.HUT)
            )
        }
        for key, (feature_id, _form) in list(self._index.items()):
            if feature_id not in huts:
                del self._index[key]


def _report_skipped(url: str, html: str, found: list[ExtractedStatement]) -> None:
    """Say which huts on a page produced no season, and what they said instead.

    Nine of the thirteen blocks yield dates; the rest publish "De début avril à
    fin septembre" or "Refuge bivouac non gardé". Those are correct to skip, and
    a run that bounds its own coverage has to say so out loud — otherwise the
    next person reads seven huts covered and has no way to tell a parser that
    is refusing prose from one that is quietly broken.
    """
    emitted = {s.payload.get("ffcam_name") for s in found}
    for name, _altitude, text in _season_blocks(HTMLParser(html)):
        if name in emitted:
            continue
        reason = (
            EXCLUDED[_norm(name)]
            if _norm(name) in EXCLUDED
            else f"no parseable dates in {' '.join(text.split())[:70]!r}"
        )
        print(f"  - {name}: {reason}")


class FfcamScraper(Scraper):
    slug = "ffcam-refuges"

    def __init__(self) -> None:
        self._huts: HutResolver | None = None

    def collect(
        self, session: Session, source: Source
    ) -> list[tuple[Document, list[ExtractedStatement]]]:
        from shapely.geometry import Point

        from massif.scripts.import_osm_huts import load_boundary

        boundary = load_boundary()
        directory = fetch(DIRECTORY)
        document, _ = store_document(session, source, DIRECTORY, directory)
        out: list[tuple[Document, list[ExtractedStatement]]] = []
        # Stored for provenance: it is the page that decides which huts are in
        # the massif at all. It carries no season blocks, so it extracts to
        # nothing, which is correct rather than a miss.
        out.append((document, []))

        seen: set[str] = set()
        skipped_outside = 0
        for row in HTMLParser(directory.text).css(".seolanMap-item"):
            try:
                point = Point(float(row.attributes["data-lng"]), float(row.attributes["data-lat"]))
            except (KeyError, TypeError, ValueError):
                continue
            if boundary is not None and not boundary.contains(point):
                skipped_outside += 1
                continue
            link = row.css_first(".plus.minisite a")
            url = (link.attributes.get("href") or "").strip() if link else ""
            if url:
                # One portal serves four directory rows. Fetching it per row
                # would hit them four times for one page.
                seen.add(url)

        print(f"{len(seen)} refuge sites in the massif ({skipped_outside} rows outside)")
        for url in sorted(seen):
            try:
                response = fetch(url)
            except Exception as error:  # noqa: BLE001 — one dead site is not a failed run
                print(f"  ! {url}: {type(error).__name__}: {error}")
                continue
            stored, _ = store_document(session, source, url, response)
            found = extract(response.text, stored.fetched_at)
            _report_skipped(url, response.text, found)
            out.append((stored, found))
        return out

    def extract_stored(self, document: Document) -> list[ExtractedStatement]:
        raw = document.raw_text or (document.raw_content or b"").decode("utf-8", "replace")
        return extract(raw, document.published_at or document.fetched_at)

    def resolve_and_build(self, session, source, document, item, resolver):
        """Match against huts only, then make it prove itself against altitude.

        Two independent screens, because each one has already been caught
        failing on its own. The hut scope is what stops "REFUGE DU GOÛTER"
        landing on the Goûter Route, which it did at a score of 100 on the
        first live run. The altitude is what stops a name from picking the
        wrong building — "Refuge Vallot" at 4322 m and "Refuge du Goûter" at
        3815 m sit on the same route with similar names.

        Every exit that is not a confirmed hut queues and returns None. It must
        never fall through to the base implementation without a slug, because
        that branch resolves against the SHARED index — the one that made the
        Goûter mistake. Falling through on failure would have applied the scope
        only when a hut had already matched, which is the case that does not
        need it: the moment FFCAM renamed a hut or listed one we do not carry,
        its season would have gone looking for a home among the routes.
        """

        def refuse(why: str) -> None:
            resolver.queue_unresolved(
                item.feature_mention,
                candidates,
                source_id=source.id,
                document_id=document.id,
                context=why,
            )
            return None

        altitude = (item.payload or {}).get("altitude_m")
        if self._huts is None:
            self._huts = HutResolver(session)
        match, candidates = self._huts.resolve(item.feature_mention)

        if match is None or match.score < NAME_FLOOR:
            return refuse(
                f"no hut reached {NAME_FLOOR:.0f} for this name; FFCAM publishes it at {altitude} m"
            )
        feature = session.get(Feature, match.feature_id)
        if feature is None:
            return refuse("matched a feature that is no longer in the table")

        ours = feature.alt_max or feature.alt_min
        if altitude is None or ours is None:
            # One screen is not two. Rather than let a name stand on its own —
            # which is how a season reached a 4808 m route — say so and let a
            # person look.
            missing = "FFCAM" if altitude is None else f"our {feature.slug}"
            return refuse(
                f"name matched {feature.slug} at {match.score:.0f} but "
                f"{missing} carries no altitude to check it against"
            )
        if abs(int(ours) - int(altitude)) > ALTITUDE_TOLERANCE_M:
            return refuse(
                f"name matched {feature.slug} at {match.score:.0f} but FFCAM "
                f"publishes {altitude} m against our {int(ours)} m"
            )

        item.feature_slug = feature.slug
        return super().resolve_and_build(session, source, document, item, resolver)


def _dump() -> int:
    """What the parser makes of the live pages, writing nothing."""
    from shapely.geometry import Point

    from massif.scripts.import_osm_huts import load_boundary

    boundary = load_boundary()
    directory = fetch(DIRECTORY)
    urls: set[str] = set()
    for row in HTMLParser(directory.text).css(".seolanMap-item"):
        try:
            point = Point(float(row.attributes["data-lng"]), float(row.attributes["data-lat"]))
        except (KeyError, TypeError, ValueError):
            continue
        if boundary is not None and not boundary.contains(point):
            continue
        link = row.css_first(".plus.minisite a")
        if link and (link.attributes.get("href") or "").strip():
            urls.add(link.attributes["href"].strip())

    print(f"{len(urls)} refuge sites inside the massif\n")
    total = 0
    for url in sorted(urls):
        try:
            page = fetch(url)
        except Exception as error:  # noqa: BLE001
            print(f"  ! {url}: {type(error).__name__}: {error}")
            continue
        found = extract(page.text, datetime.now(UTC))
        total += len(found)
        blocks = _season_blocks(HTMLParser(page.text))
        for name, altitude, text in blocks:
            mine = [s for s in found if s.payload.get("ffcam_name") == name]
            if _norm(name) in EXCLUDED:
                note = f"EXCLUDED — {EXCLUDED[_norm(name)]}"
            elif not mine:
                note = f"no dated season: {' '.join(text.split())[:60]!r}"
            else:
                note = "; ".join(
                    f"{s.payload['season']} {s.valid_from:%d %b %Y} – {s.valid_to:%d %b %Y}"
                    for s in mine
                )
            print(f"  {name[:34]:36} {str(altitude or '?'):>5} m  {note}")
    print(f"\n{total} dated seasons")
    return 0


if __name__ == "__main__":
    raise SystemExit(_dump())
