"""Hut facts from camptocamp.org, matched by position.

    python -m massif.scripts.import_camptocamp_facts            # dry run
    python -m massif.scripts.import_camptocamp_facts --apply

WHY A SECOND FACTS SOURCE. refuges.info is a French project and answers "is
there water, how many places". camptocamp covers France, Italy and Switzerland
with one schema and answers a different question: `custodianship`, a structured
enum saying whether a hut is always accessible, open only when the warden is
there, or unwardened. That is the closest thing anyone publishes to a standing
state for a hut, and it is the single most useful thing missing from the pages.

It does NOT make a hut's status known. custodianship is a property of the
arrangement, not a dated claim about today, so it goes to feature_facts and
never near the status pipeline — the same line CLAUDE.md draws between the
warden season (a statement) and the bunk count (a fact). Huts stay "unknown"
until somebody publishes a dated claim, because nobody does.

MATCHED BY POSITION, not by name. Their names are trilingual and ours are
whichever language we picked — "Rifugio Torino" against "Refuge Torino" cost a
day already. Two hut records within 150 m are one building, and that check does
not care what language anybody wrote it in. Altitude is a second opinion.

Collaborative documents are CC-BY-SA (coordinates also ODbL), so every fact row
carries the permalink and the licence travels with it in fetch_config.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from datetime import UTC, datetime

import httpx
from sqlalchemy import select, text

from massif.db import session_scope
from massif.ingest.hut_facts import is_decoy
from massif.models import FeatureFact, Source

SOURCE_SLUG = "camptocamp"
API = "https://api.camptocamp.org"
# EPSG:3857, the massif generously. Their API takes web mercator, not degrees.
BBOX = "745000,5745000,795000,5800000"
PERMALINK = "https://www.camptocamp.org/waypoints/{id}"

REFRESH_DAYS = 7
# Two hut records this close are one building. Same figure as the OSM importer,
# and for the same reason.
MATCH_METRES = 150
# A second opinion on the position match. Wider than the OSM importer's 120 m
# because the two projects survey independently and disagree by tens of metres
# on huts that are plainly the same building.
ALTITUDE_TOLERANCE_M = 200

# Their enum, in English. The wording matters more than it looks, because this
# renders on a public page as though we had checked it.
#
# "always_accessible" does NOT mean the refuge is open for business. It is the
# custodianship field — access RELATIVE TO THE WARDEN — and it marks huts with
# shelter you can reach when nobody is there. Tête Rousse and the Couvercle
# both carry it, and both have a separate winter refuge that OSM maps as its
# own building; the Requin, which does not, is accessible_when_wardened. That
# is inference from the data, not from their documentation: their UI strings
# are not in the bundles they serve, so this reading is the most conservative
# one the evidence supports, and it deliberately claims less than "open".
#
# Unrecognised values are DROPPED rather than passed through. A word we have
# not seen is a word we cannot promise we understand.
CUSTODIANSHIP = {
    "always_accessible": "Some shelter accessible even when unwardened",
    "accessible_when_wardened": "Open only when the warden is there",
    "closed_when_unwardened": "Closed when the warden is away",
    "no_warden": "No warden",
}


def lonlat(document: dict) -> tuple[float, float] | None:
    """Their geometry is web mercator inside a JSON string."""
    raw = (document.get("geometry") or {}).get("geom")
    if not raw:
        return None
    try:
        x, y = json.loads(raw)["coordinates"]
    except Exception:
        return None
    lon = x / 20037508.34 * 180
    lat = math.degrees(2 * math.atan(math.exp(y / 20037508.34 * math.pi)) - math.pi / 2)
    return lat, lon


def metres(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(
        (a[0] - b[0]) * 111_000,
        (a[1] - b[1]) * 111_000 * math.cos(math.radians(a[0])),
    )


def _int(value) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    # They use 0 for "not recorded" exactly as refuges.info uses it for places.
    return number if number > 0 else None


def read_hut(full: dict) -> dict:
    """One camptocamp waypoint, reduced to what we keep.

    Deliberately not `description`, `access` or `access_period`. That is their
    community's writing, and copying it is what their licence asks us not to do
    casually — we link instead. access_period in particular is tempting because
    it holds the warden season, but it is free prose in three languages and
    reading it with a regex would be guessing.
    """
    locale = (full.get("locales") or [{}])[0]
    custodianship = CUSTODIANSHIP.get(full.get("custodianship") or "")
    facts = {
        "name_local": (locale.get("title") or "").strip() or None,
        "custodianship": custodianship,
        "capacity_staffed": _int(full.get("capacity_staffed")),
        "capacity_unstaffed": _int(full.get("capacity")),
        "phone": (full.get("phone") or "").strip() or None,
        "altitude_m": _int(full.get("elevation")),
        "operator_url": (full.get("url") or "").strip() or None,
    }
    return {k: v for k, v in facts.items() if v is not None}


def fetch_index(client: httpx.Client) -> list[dict]:
    documents: list[dict] = []
    offset = 0
    while True:
        response = client.get(
            f"{API}/waypoints",
            params={"wtyp": "hut", "bbox": BBOX, "limit": 100, "offset": offset},
            timeout=90,
        )
        response.raise_for_status()
        body = response.json()
        batch = body.get("documents") or []
        documents.extend(batch)
        offset += len(batch)
        if not batch or offset >= (body.get("total") or 0):
            return documents


def _due(session, force: bool) -> bool:
    if force:
        return True
    source = session.scalar(select(Source).where(Source.slug == SOURCE_SLUG))
    if source is None:
        return True
    newest = session.scalar(
        select(FeatureFact.fetched_at)
        .where(FeatureFact.source_id == source.id)
        .order_by(FeatureFact.fetched_at.desc())
    )
    if newest is None:
        return True
    return (datetime.now(UTC) - newest).days >= REFRESH_DAYS


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write; otherwise dry run")
    parser.add_argument("--force", action="store_true", help="fetch even if not due")
    args = parser.parse_args()

    with session_scope() as session:
        source = session.scalar(select(Source).where(Source.slug == SOURCE_SLUG))
        if source is None:
            print(f"source {SOURCE_SLUG!r} not seeded — add it to seeds/sources.yaml")
            return 1
        if not _due(session, args.force):
            print(f"{SOURCE_SLUG}: last pull is under {REFRESH_DAYS} days old, nothing to do")
            return 0

        ours = session.execute(
            text(
                "SELECT id, slug, name_default, alt_max, alt_min, "
                "ST_Y(geom::geometry) lat, ST_X(geom::geometry) lon "
                "FROM features WHERE feature_type='hut' AND active AND geom IS NOT NULL "
                "ORDER BY slug"
            )
        ).all()

        headers = {"User-Agent": "massif/0.1 hut facts (+https://github.com/Deltaspace2/massif)"}
        with httpx.Client(headers=headers) as client:
            index = fetch_index(client)
            print(f"{SOURCE_SLUG}: {len(index)} huts in the bbox")

            placed = [(d, lonlat(d)) for d in index]
            placed = [(d, p) for d, p in placed if p]

            matched = unmatched = 0
            for hut in ours:
                best = None
                for document, point in placed:
                    title = (document.get("locales") or [{}])[0].get("title") or ""
                    # A superseded building is not this building, however close.
                    if is_decoy(title):
                        continue
                    distance = metres((hut.lat, hut.lon), point)
                    if best is None or distance < best[0]:
                        best = (distance, document, title)
                if best is None or best[0] > MATCH_METRES:
                    unmatched += 1
                    print(f"  --   {hut.slug:40} nothing within {MATCH_METRES} m")
                    continue

                distance, document, title = best
                ours_alt = hut.alt_max or hut.alt_min
                theirs_alt = _int(document.get("elevation"))
                if (
                    ours_alt is not None
                    and theirs_alt is not None
                    and abs(theirs_alt - ours_alt) > ALTITUDE_TOLERANCE_M
                ):
                    unmatched += 1
                    print(
                        f"  --   {hut.slug:40} {distance:.0f} m away but "
                        f"{abs(theirs_alt - ours_alt)} m of altitude apart"
                    )
                    continue

                time.sleep(0.4)  # their API, our manners
                full = client.get(f"{API}/waypoints/{document['document_id']}", timeout=60).json()
                payload = read_hut(full)
                if not payload:
                    unmatched += 1
                    print(f"  --   {hut.slug:40} matched but publishes nothing we keep")
                    continue

                matched += 1
                print(
                    f"  ok   {hut.slug:40} -> {title[:30]:32} "
                    f"{distance:3.0f} m  {payload.get('custodianship') or ''}"
                )
                if not args.apply:
                    continue

                row = session.scalar(
                    select(FeatureFact).where(
                        FeatureFact.feature_id == hut.id,
                        FeatureFact.source_id == source.id,
                    )
                ) or FeatureFact(feature_id=hut.id, source_id=source.id)
                row.external_ref = str(document["document_id"])
                row.source_url = PERMALINK.format(id=document["document_id"])
                row.payload = payload
                row.source_modified_at = None
                row.fetched_at = datetime.now(UTC)
                row.match_method = "position"
                row.match_score = round(max(0.0, 100.0 - distance), 2)
                session.add(row)

        verb = "wrote" if args.apply else "would write"
        print(f"\n{SOURCE_SLUG}: {verb} {matched} of {len(ours)} huts, {unmatched} unmatched")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
