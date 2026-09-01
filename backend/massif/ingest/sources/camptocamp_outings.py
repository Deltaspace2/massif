"""camptocamp route conditions — the `condition_rating` on dated trip reports.

    python -m massif.ingest.sources.camptocamp_outings     # dry run, no DB

WHY THIS EXISTS, AND THE TENSION IT SITS IN. CLAUDE.md lists "crowd-sourced
condition reports" under Not in v1, with "do not start them until v1 has run a
full season". This was built anyway, on an explicit instruction to get route
status checked weekly, after the two in-scope alternatives were reconned and
found empty: La Chamoniarde publishes nobody's data but other people's, and the
préfecture's mountain output is avalanche vigilance plus one access ban whose
body is a PDF. If that call is unwanted, `active: false` in seeds/sources.yaml
turns it off and nothing else has to change.

WHAT IT IS AND IS NOT. A trip report is one person saying what they found on a
day. It is NOT a closure, and nothing here ever produces one: every statement
is `condition` at status UNKNOWN, so a route's badge is untouched and only its
notices gain a line. "Poor conditions" is not "closed", and a site that let a
community rating drive a red dot would be inventing closures out of opinions.

The rating is a STRUCTURED field — excellent / good / average / poor — which is
why this is a rule-based parser and not an LLM one. Their prose is never read,
only the enum, the date and the title, exactly as the facts importer takes
capacity and not the description.

STALENESS IS THE POINT, NOT A FLAW. STALE_DAYS already answers `condition` with
14 days, which is short and correct: a report from three weeks ago describes a
mountain that has since had weather. Most of these will render greyed almost
immediately. Measured on 1 Sep 2026, only 2 of our 13 routes had ANY report in
the previous 90 days — the Goulotte Chéré has 299 lifetime reports and nothing
since April, because it is an ice route in September. This source is honest
about a mountain nobody has been on lately, which is most of them, most of the
time.

ATTRIBUTION. CC BY-SA, so every statement carries the permalink to the outing
whose author wrote it — per report, never one shared footer, the same condition
the facts block is built around.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from massif.enums import ExtractionMethod, FeatureType, StatementType, StatusValue
from massif.ingest.base import ExtractedStatement, Scraper, store_document
from massif.models import Document, Feature, Source

API = "https://api.camptocamp.org"
PERMALINK = "https://www.camptocamp.org/outings/{id}"
UA = "massif/0.1 route conditions (+https://github.com/Deltaspace2/massif)"

# Their enum, in English already. A value we do not recognise emits nothing:
# inventing a phrase for a rating we have never seen is how a parser starts
# saying things its source did not.
RATINGS = {
    "excellent": "excellent",
    "good": "good",
    "average": "mixed",
    "poor": "poor",
    "awful": "very poor",
}

# Older than this and we do not carry it at all. STALE_DAYS greys a condition
# at 14 days; importing a report from last spring would put a permanently grey
# line on a route page and call it coverage.
RECENT_DAYS = 30


def _client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": UA}, timeout=60)


def pinned_route(feature: Feature) -> int | None:
    """The camptocamp route id a human pinned to this feature, or None.

    NO SEARCHING. An earlier version looked their routes up by name and made
    each candidate clear an altitude check, and it was not nearly enough:
    our Goûter route matched the Kungsleden in Sweden on our own alias "Voie
    Royale", and with the altitude gate tightened the Grand Couloir still
    matched an unrelated "Couloir Rectiligne", because altitude cannot separate
    two couloirs at the same height. A search endpoint ranks strings; it has no
    idea which mountain you mean, and CLAUDE.md's eighth rule is exactly this.

    So the mapping is curated in seeds/features_curated.yaml, one line per
    route, and this source can only ever speak about a route someone checked.
    Nine of our thirteen are pinned; the other four had no unambiguous match
    and are better silent than guessed at.
    """
    return (feature.external_ids or {}).get("camptocamp_route")


def _title(document: dict) -> str:
    for locale in document.get("locales") or []:
        if locale.get("title"):
            return locale["title"]
    return ""


def extract(raw: str, observed_at: datetime) -> list[ExtractedStatement]:
    """The newest usable report in one stored envelope.

    One statement per route per run, from the freshest report that carries a
    rating. Emitting every recent outing would put ten near-identical lines on
    the Cosmiques and none anywhere else, which describes camptocamp's traffic
    rather than the mountain.
    """
    envelope = json.loads(raw)
    slug = envelope["feature_slug"]
    cutoff = observed_at.date() - timedelta(days=RECENT_DAYS)

    usable = []
    for outing in envelope.get("outings") or []:
        rating = outing.get("condition_rating")
        started = outing.get("date_start")
        if not rating or not started:
            continue
        if rating not in RATINGS:
            print(f"  - {slug}: unrecognised condition_rating {rating!r}, skipped")
            continue
        try:
            when = date.fromisoformat(started)
        except ValueError:
            continue
        if when < cutoff:
            continue
        usable.append((when, outing))

    if not usable:
        return []
    usable.sort(key=lambda pair: pair[0], reverse=True)
    when, outing = usable[0]
    if len(usable) > 1:
        # No silent caps: say what was set aside and why.
        print(f"  - {slug}: {len(usable)} recent reports, carrying the newest only")

    reported = datetime(when.year, when.month, when.day, tzinfo=UTC)
    rating = RATINGS[outing["condition_rating"]]
    return [
        ExtractedStatement(
            feature_mention=envelope.get("route_title") or slug,
            feature_slug=slug,
            statement_type=StatementType.CONDITION,
            # Never a closure. One person's report of a day on the mountain
            # says nothing about whether the route is open.
            status=StatusValue.UNKNOWN,
            severity=0,
            observed_at=reported,
            valid_from=reported,
            valid_to=reported + timedelta(days=RECENT_DAYS),
            summary_en=f"Conditions reported {rating} on {when:%d %b %Y}",
            original_text=_title(outing),
            original_language="fr",
            extraction_method=ExtractionMethod.RULE,
            payload={
                "advisory": True,
                "condition_rating": outing["condition_rating"],
                "permalink": PERMALINK.format(id=outing["document_id"]),
                "recent_reports": len(usable),
            },
        )
    ]


class CamptocampOutingsScraper(Scraper):
    slug = "camptocamp-outings"

    def collect(
        self, session: Session, source: Source
    ) -> list[tuple[Document, list[ExtractedStatement]]]:
        routes = list(
            session.scalars(
                select(Feature)
                .where(
                    Feature.feature_type.in_([FeatureType.ROUTE, FeatureType.COULOIR]),
                    Feature.active.is_(True),
                )
                .order_by(Feature.slug)
            )
        )
        out: list[tuple[Document, list[ExtractedStatement]]] = []
        unmatched: list[str] = []

        with _client() as client:
            for feature in routes:
                route_id = pinned_route(feature)
                if not route_id:
                    unmatched.append(feature.slug)
                    continue
                title = (feature.external_ids or {}).get("camptocamp_title")

                url = f"{API}/outings?r={route_id}"
                try:
                    payload = client.get(f"{API}/outings", params={"r": route_id, "limit": 40})
                    payload.raise_for_status()
                except Exception as error:  # noqa: BLE001
                    print(f"  ! {feature.slug}: {type(error).__name__}: {error}")
                    continue

                # Stored with the identity we queried for. The response alone
                # does not say which of our routes it is about, and a document
                # that cannot be re-extracted on its own defeats the point of
                # storing it.
                envelope = json.dumps(
                    {
                        "feature_slug": feature.slug,
                        "route_id": route_id,
                        "route_title": title,
                        "outings": payload.json().get("documents") or [],
                    },
                    ensure_ascii=False,
                )
                document, _ = store_document(session, source, url, payload, raw_text=envelope)
                out.append((document, extract(envelope, document.fetched_at)))

        if unmatched:
            # No silent caps. Most of these are ours to fix: a route with no
            # alt_max cannot be checked against theirs, so it is never matched.
            # No silent caps. These are routes nobody has pinned, and the fix
            # is a curated line, not a looser matcher.
            print(f"  {len(unmatched)} routes carry no camptocamp pin: {', '.join(unmatched)}")
        return out

    def extract_stored(self, document: Document) -> list[ExtractedStatement]:
        raw = document.raw_text or (document.raw_content or b"").decode("utf-8", "replace")
        return extract(raw, document.published_at or document.fetched_at)


def _dump() -> int:
    """What the parser makes of the live API, writing nothing."""
    from massif.db import SessionLocal

    now = datetime.now(UTC)
    with SessionLocal() as session, _client() as client:
        routes = list(
            session.scalars(
                select(Feature)
                .where(
                    Feature.feature_type.in_([FeatureType.ROUTE, FeatureType.COULOIR]),
                    Feature.active.is_(True),
                )
                .order_by(Feature.slug)
            )
        )
        carried = 0
        pinned = 0
        for feature in routes:
            route_id = pinned_route(feature)
            if not route_id:
                print(f"  {feature.slug[:28]:30} {'—':34} not pinned")
                continue
            pinned += 1
            outings = client.get(f"{API}/outings", params={"r": route_id, "limit": 40}).json()
            envelope = json.dumps(
                {
                    "feature_slug": feature.slug,
                    "route_title": (feature.external_ids or {}).get("camptocamp_title"),
                    "outings": outings.get("documents") or [],
                },
                ensure_ascii=False,
            )
            found = extract(envelope, now)
            carried += len(found)
            said = found[0].summary_en if found else "nothing in the last 30 days"
            total = len(outings.get("documents") or [])
            print(f"  {feature.slug[:28]:30} r={route_id:<8} {total:>3} reports  {said}")
        print(
            f"\n{carried} of {pinned} pinned routes carry a recent report "
            f"({len(routes)} routes in total)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(_dump())
