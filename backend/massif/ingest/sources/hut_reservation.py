"""Swiss hut seasons from the CAS booking platform's public availability.

    python -m massif.ingest.sources.hut_reservation     # dry run, no DB

WHAT THIS IS. hut-reservation.org is the booking system the Swiss Alpine Club
runs, and one endpoint on it needs no login:

    /api/v1/reservation/getHutAvailability?hutId=N

It answers with 731 days — two full years — of one field per date:

    SERVICED     the warden is there
    UNSERVICED   open, but nobody is running it
    CLOSED       shut

That is a dated, structured, per-day statement of a hut's season from the
operator's own system, which is the best kind of source this project can have
and the only one of its shape we have found for huts. Everything else we tried
for the wardened huts was prose on 25 separate websites.

WHY ONLY THREE HUTS. Because only three of ours are on it: Trient, Orny and
Saleinaz. Their own sites link the booking page and the id is in that URL, so
the ids were found by reading each hut's site once rather than by walking the
platform's id space, which would be a lot of requests aimed at somebody else's
server for a handful of answers. The other 35 wardened huts in the massif
either use a different booking system or take bookings by telephone. If more
of them join, adding a line to features_curated.yaml is the whole change.

IDS ARE CURATED AND VALIDATED. `/reservation/hutInfo/N` is also public and
returns the name, country and altitude, so every id in the seed was checked
against our own record before being written down — Trient 3170 m against their
3170, Orny 2826 against 2831, Saleinaz 2691 against 2691. A booking id lifted
from a web page is a claim like any other.

CLOSED IS ROUTINE HERE, NOT NEWS. A Swiss hut is shut for most of the winter
and that is the ordinary state of the world, so it carries
`closure_kind: outside_hours` and renders grey rather than red. Ten huts asleep
for the season must not look like a mountain that fell down.
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

API = "https://www.hut-reservation.org/api/v1/reservation"
UA = "massif/0.1 hut seasons (+https://github.com/Deltaspace2/massif)"

# Their field, and what each value means for us. A value we do not recognise
# emits nothing rather than being guessed at.
STATES: dict[str, tuple[StatementType, StatusValue, str, bool]] = {
    "SERVICED": (
        StatementType.OPENING,
        StatusValue.OPEN,
        "Wardened — the operator's booking system shows the warden on site",
        False,
    ),
    "UNSERVICED": (
        StatementType.OPENING,
        StatusValue.OPEN,
        "Open but unstaffed — no warden on site, self-catering only",
        False,
    ),
    "CLOSED": (
        StatementType.CLOSURE,
        StatusValue.CLOSED,
        "Closed for the season",
        True,
    ),
}


def _client() -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": UA, "Accept": "application/json"},
        timeout=45,
        follow_redirects=True,
    )


def _days(entries: list[dict]) -> list[tuple[date, str]]:
    """Their calendar, reduced to days we are willing to believe.

    `hutStatus` ALONE IS NOT A SEASON, and taking it at face value would have
    published something absurd. The Cabane du Trient reads SERVICED on every
    day from September 2026 to September 2027 — through the whole winter — and
    the hut is plainly not wardened in January. What separates the real days
    from the rest is `freeBeds`: it is a number for days inside the bookable
    window and null everywhere else. Trient's nulls run from October to March,
    which is exactly the winter the SERVICED flag was papering over.

    So an open state needs a bed count behind it. A day with neither is not a
    quiet "closed" — it is no information, and it BREAKS a run rather than
    extending one, so a season can never be stretched across a gap we cannot
    see into.

    CLOSED is kept as it stands: there is nothing to book on a day the hut is
    shut, so a null bed count there is the expected shape of a real claim
    rather than the absence of one.
    """
    out: list[tuple[date, str]] = []
    for entry in entries:
        raw, state = entry.get("date"), entry.get("hutStatus")
        if not raw or not state:
            continue
        if state != "CLOSED" and entry.get("freeBeds") is None:
            continue
        try:
            out.append((datetime.fromisoformat(raw.replace("Z", "+00:00")).date(), state))
        except ValueError:
            continue
    out.sort()
    return out


def run_around(days: list[tuple[date, str]], on: date) -> tuple[str, date, date] | None:
    """The unbroken stretch of one state containing `on`.

    A calendar of 731 individual days is not 731 statements — it is a handful
    of seasons. This collapses it to the one the reference date falls in, which
    is the only one that can be in force, and gives it real bounds so it
    expires on its own terms instead of on a staleness rule.
    """
    index = {day: state for day, state in days}
    state = index.get(on)
    if state is None:
        return None
    start = end = on
    while index.get(start - timedelta(days=1)) == state:
        start -= timedelta(days=1)
    while index.get(end + timedelta(days=1)) == state:
        end += timedelta(days=1)
    return state, start, end


def extract(raw: str, observed_at: datetime) -> list[ExtractedStatement]:
    envelope = json.loads(raw)
    slug = envelope["feature_slug"]
    days = _days(envelope.get("availability") or [])
    # The day the document speaks for. Never now(): re-extracting a stored
    # calendar has to reproduce the season that was current when we fetched it.
    found = run_around(days, observed_at.date())
    if found is None:
        print(f"  - {slug}: the calendar does not cover {observed_at.date()}")
        return []

    state, start, end = found
    mapped = STATES.get(state)
    if mapped is None:
        print(f"  - {slug}: unrecognised hutStatus {state!r}, skipped")
        return []

    statement_type, status, summary, routine = mapped
    payload: dict = {"hut_status": state, "hut_id": envelope.get("hut_id")}
    if state == "SERVICED":
        # Lets the page say "Wardened until 19 Sep" rather than "Open since
        # 1 Sep". For a hut the end is the half a reader plans around, and
        # here it is the operator's own date rather than our widening.
        payload["wardened"] = True
    if routine:
        # Shut because it is the season, not because anything happened.
        payload["closure_kind"] = "outside_hours"
    return [
        ExtractedStatement(
            feature_mention=envelope.get("hut_name") or slug,
            feature_slug=slug,
            statement_type=statement_type,
            status=status,
            severity=0,
            observed_at=observed_at,
            valid_from=datetime(start.year, start.month, start.day, tzinfo=UTC),
            valid_to=datetime(end.year, end.month, end.day, 23, 59, 59, tzinfo=UTC),
            summary_en=summary,
            original_text=f"{state} {start:%d.%m.%Y}–{end:%d.%m.%Y}",
            original_language="en",
            extraction_method=ExtractionMethod.RULE,
            payload=payload,
        )
    ]


class HutReservationScraper(Scraper):
    slug = "hut-reservation"

    def collect(
        self, session: Session, source: Source
    ) -> list[tuple[Document, list[ExtractedStatement]]]:
        huts = session.scalars(
            select(Feature).where(Feature.feature_type == FeatureType.HUT, Feature.active.is_(True))
        ).all()
        out: list[tuple[Document, list[ExtractedStatement]]] = []
        with _client() as client:
            for hut in huts:
                hut_id = (hut.external_ids or {}).get("hut_reservation")
                if not hut_id:
                    continue
                url = f"{API}/getHutAvailability?hutId={hut_id}"
                try:
                    response = client.get(url)
                    response.raise_for_status()
                except Exception as error:  # noqa: BLE001 — one hut is not the run
                    print(f"  ! {hut.slug}: {type(error).__name__}: {error}")
                    continue
                # Stored with the hut it was fetched for: the calendar itself
                # never says which hut it is, and a document that cannot be
                # re-extracted alone defeats the point of storing it.
                envelope = json.dumps(
                    {
                        "feature_slug": hut.slug,
                        "hut_id": hut_id,
                        "hut_name": hut.name_default,
                        "availability": response.json(),
                    },
                    ensure_ascii=False,
                )
                document, _ = store_document(session, source, url, response, raw_text=envelope)
                out.append((document, extract(envelope, document.fetched_at)))
        if not out:
            print("  ! no huts carry a hut_reservation id — nothing to fetch")
        return out

    def extract_stored(self, document: Document) -> list[ExtractedStatement]:
        raw = document.raw_text or (document.raw_content or b"").decode("utf-8", "replace")
        return extract(raw, document.published_at or document.fetched_at)


def _dump() -> int:
    """What the parser makes of the live API, writing nothing."""
    from massif.db import SessionLocal

    now = datetime.now(UTC)
    with SessionLocal() as session, _client() as client:
        huts = session.scalars(
            select(Feature).where(Feature.feature_type == FeatureType.HUT, Feature.active.is_(True))
        ).all()
        seen = 0
        for hut in huts:
            hut_id = (hut.external_ids or {}).get("hut_reservation")
            if not hut_id:
                continue
            seen += 1
            data = client.get(f"{API}/getHutAvailability?hutId={hut_id}").json()
            envelope = json.dumps(
                {
                    "feature_slug": hut.slug,
                    "hut_id": hut_id,
                    "hut_name": hut.name_default,
                    "availability": data,
                }
            )
            for statement in extract(envelope, now):
                print(
                    f"  {hut.slug[:26]:28} {statement.original_text:30} "
                    f"{statement.status.value:8} {statement.summary_en[:44]}"
                )
        print(f"\n{seen} huts carry a hut_reservation id")
    return 0


if __name__ == "__main__":
    raise SystemExit(_dump())
