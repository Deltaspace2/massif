"""Pull hut facts from refuges.info and attach them to our features.

    python -m massif.scripts.import_hut_facts            # dry run
    python -m massif.scripts.import_hut_facts --apply
    python -m massif.scripts.import_hut_facts --apply --force

ONE request. Their bbox API returns the whole massif in a single response, so a
weekly refresh costs them fifty-two requests a year — against a site whose
robots.txt records sixty thousand bot page-loads a day. The cadence lives in
the data rather than in the cron: this exits without fetching unless the last
successful pull is older than REFRESH_DAYS, so it is safe to call from an
hourly workflow and will do nothing 167 times out of 168.

Structured fields only, never their prose, and every fact carries a link back
to the entry whose community wrote it. CC BY-SA 2.0.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from massif.db import session_scope
from massif.ingest.base import fetch
from massif.ingest.hut_facts import Candidate, match_candidate, read_candidate
from massif.models import Feature, FeatureFact, Source

SOURCE_SLUG = "refuges-info"

# The massif, generously. One box, one request.
BBOX = "6.70,45.75,7.05,46.02"
API = (
    "https://www.refuges.info/api/bbox"
    f"?bbox={BBOX}&type_points=refuge,cabane,gite,abri"
    "&format=geojson&detail=complet"
)

REFRESH_DAYS = 7


def _due(session, force: bool) -> bool:
    if force:
        return True
    newest = session.scalar(select(FeatureFact.fetched_at).order_by(FeatureFact.fetched_at.desc()))
    if newest is None:
        return True
    return newest < datetime.now(UTC) - timedelta(days=REFRESH_DAYS)


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
            print(
                f"{SOURCE_SLUG}: last pull is under {REFRESH_DAYS} days old, "
                "nothing to do (--force to override)"
            )
            return 0

        response = fetch(API)
        payload = response.json()
        candidates: list[Candidate] = [
            c for c in (read_candidate(f) for f in payload.get("features", [])) if c
        ]
        print(f"{SOURCE_SLUG}: {len(candidates)} entries in the bbox")

        huts = session.scalars(
            select(Feature).where(Feature.feature_type == "hut").order_by(Feature.slug)
        ).all()

        now = datetime.now(UTC)
        matched = unmatched = 0

        for hut in huts:
            curated = (hut.external_ids or {}).get(SOURCE_SLUG)
            altitude = hut.alt_max or hut.alt_min
            match = match_candidate(
                hut.name_default, altitude, candidates, curated_ref=curated
            )
            if match is None:
                unmatched += 1
                print(f"  --   {hut.slug:28} no entry")
                continue

            matched += 1
            payload_out = dict(match.candidate.payload)
            print(
                f"  ok   {hut.slug:28} -> {match.candidate.name[:30]:30} "
                f"({match.method} {match.score:.0f}) "
                f"places={payload_out.get('capacity')}"
            )
            if not args.apply:
                continue

            row = session.scalar(
                select(FeatureFact).where(
                    FeatureFact.feature_id == hut.id,
                    FeatureFact.source_id == source.id,
                )
            ) or FeatureFact(feature_id=hut.id, source_id=source.id)
            row.external_ref = match.candidate.external_ref
            row.source_url = match.candidate.url
            row.payload = payload_out
            row.source_modified_at = _parse(match.candidate.modified_at)
            row.fetched_at = now
            row.match_method = match.method
            row.match_score = round(match.score, 2)
            session.add(row)

        verb = "wrote" if args.apply else "would write"
        print(
            f"{SOURCE_SLUG}: {verb} {matched} of {len(huts)} huts, "
            f"{unmatched} with no entry (the Italian side is not covered — "
            "refuges.info is a French project, and saying so beats a nearest guess)"
        )
        return 0


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


if __name__ == "__main__":
    raise SystemExit(main())
