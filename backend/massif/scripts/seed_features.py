"""Seed sources and features, and merge OSM coordinates into curated entries.

Idempotent: re-running updates in place rather than duplicating. Curated
fields always win over OSM — OSM supplies geometry, the YAML supplies identity.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import yaml
from sqlalchemy import select

from massif.db import session_scope
from massif.ingest.resolve import normalise
from massif.models import Feature, Source

SEEDS = Path(__file__).resolve().parents[2] / "seeds"


def load(name: str) -> list[dict]:
    path = SEEDS / name
    if not path.exists():
        return []
    return yaml.safe_load(path.read_text(encoding="utf-8")) or []


def seed_sources(session) -> int:
    count = 0
    for row in load("sources.yaml"):
        notes = row.pop("notes", None)
        existing = session.scalar(select(Source).where(Source.slug == row["slug"]))
        if existing is None:
            existing = Source(slug=row["slug"])
            session.add(existing)
        existing.name = row["name"]
        existing.url = row["url"]
        existing.source_type = row["source_type"]
        existing.language = row["language"]
        existing.country = row.get("country")
        existing.trust_weight = Decimal(str(row.get("trust_weight", 0.5)))
        existing.fetch_interval_minutes = row.get("fetch_interval_minutes", 360)
        existing.active = row.get("active", True)
        existing.fetch_config = {"notes": notes} if notes else {}
        count += 1
    return count


def build_osm_index() -> dict[str, dict]:
    """Normalised name -> OSM candidate."""
    index: dict[str, dict] = {}
    for candidate in load("osm_candidates.yaml"):
        forms = [candidate["name_default"], *(candidate.get("names") or {}).values()]
        forms.extend(candidate.get("aliases") or [])
        for form in forms:
            key = normalise(form)
            if key:
                index.setdefault(key, candidate)
    return index


def seed_features(session) -> tuple[int, int]:
    osm = build_osm_index()
    curated = load("features_curated.yaml")

    seeded = 0
    matched = 0
    parents: dict[str, str] = {}

    for row in curated:
        existing = session.scalar(select(Feature).where(Feature.slug == row["slug"]))
        if existing is None:
            existing = Feature(slug=row["slug"])
            session.add(existing)

        existing.feature_type = row["feature_type"]
        existing.name_default = row["name_default"]
        existing.names = row.get("names") or {}
        existing.aliases = row.get("aliases") or []
        existing.alt_min = row.get("alt_min")
        existing.alt_max = row.get("alt_max")
        existing.country = row.get("country")
        existing.notes = row.get("notes")

        # OSM supplies geometry only
        for form in [row["name_default"], *existing.aliases]:
            candidate = osm.get(normalise(form))
            if candidate:
                existing.geom = (
                    f"SRID=4326;POINT({candidate['lon']} {candidate['lat']})"
                )
                existing.geom_verified = False
                existing.external_ids = {
                    **(existing.external_ids or {}),
                    "osm": candidate["osm_id"],
                }
                matched += 1
                break

        if row.get("parent"):
            parents[row["slug"]] = row["parent"]
        seeded += 1

    session.flush()

    for child_slug, parent_slug in parents.items():
        child = session.scalar(select(Feature).where(Feature.slug == child_slug))
        parent = session.scalar(select(Feature).where(Feature.slug == parent_slug))
        if child and parent:
            child.parent_id = parent.id

    return seeded, matched


def main() -> int:
    with session_scope() as session:
        n_sources = seed_sources(session)
        n_features, n_matched = seed_features(session)

    print(f"sources:  {n_sources}")
    print(f"features: {n_features} seeded, {n_matched} matched to OSM geometry")
    unmatched = n_features - n_matched
    if unmatched:
        print(
            f"\n{unmatched} features have no geometry yet — expected for routes "
            f"and couloirs, which OSM does not carry usefully.",
            file=sys.stderr,
        )
    print(
        "\nAll geometry is geom_verified=false until checked against IGN.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
