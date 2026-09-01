"""Seed sources and features, and merge OSM coordinates into curated entries.

Idempotent: re-running updates in place rather than duplicating. Curated
fields always win over OSM — OSM supplies geometry, the YAML supplies identity.
"""

from __future__ import annotations

import re
import sys
import unicodedata
from decimal import Decimal
from pathlib import Path

import yaml
from sqlalchemy import select

from massif.db import session_scope
from massif.models import Feature, Source


# Deliberately NOT massif.ingest.resolve.normalise. That one strips generic
# mountain nouns (route, voie, arête, refuge, du) so prose mentions match
# loosely — which is exactly wrong here. Under it, "Goûter Route" and "Refuge
# du Goûter" are the same string, and the route inherited the hut's location.
# Geometry assignment wants the strictest match we can manage, not the
# loosest: casefold, strip accents, collapse whitespace, nothing else.
def geo_key(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-z0-9\s]", " ", text.casefold())
    return re.sub(r"\s+", " ", text).strip()


# Feature kinds that ARE a point. A route or a couloir is a line; giving it a
# point is the wrong shape even when the name matches correctly, so they are
# never assigned OSM point geometry.
POINT_LIKE = {"hut", "lift", "lift_station", "peak"}

SEEDS = Path(__file__).resolve().parents[2] / "seeds"


def metres(value: object) -> int | None:
    """OSM `ele` is a free-text tag, not a number. "3678", "3678 m", "3678.5",
    "" and a missing key all occur, and a hut is not worth crashing a seed run
    over. Anything unreadable is no altitude, which is what we had before."""
    try:
        return int(float(str(value).split()[0]))
    except (AttributeError, IndexError, TypeError, ValueError):
        return None


def load(name: str) -> list[dict]:
    path = SEEDS / name
    if not path.exists():
        return []
    return yaml.safe_load(path.read_text(encoding="utf-8")) or []


def seed_sources(session) -> int:
    count = 0
    for row in load("sources.yaml"):
        notes = row.pop("notes", None)
        licence = row.pop("licence", None)
        licence_url = row.pop("licence_url", None)
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
        # Licence travels with the source rather than living in the renderer:
        # the next facts source that forgets it must fail loudly by rendering
        # no attribution block, not quietly by rendering one without a credit.
        config: dict = {}
        if notes:
            config["notes"] = notes
        if licence:
            config["licence"] = licence
        if licence_url:
            config["licence_url"] = licence_url
        existing.fetch_config = config
        count += 1
    return count


def build_osm_index() -> dict[str, dict]:
    """Normalised name -> OSM candidate."""
    index: dict[str, dict] = {}
    for candidate in load("osm_candidates.yaml"):
        forms = [candidate["name_default"], *(candidate.get("names") or {}).values()]
        forms.extend(candidate.get("aliases") or [])
        for form in forms:
            key = geo_key(form)
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

        # A human decided these, so they outrank anything matching can infer.
        # Merged, not assigned: the OSM step below adds its own key, and the
        # two must not overwrite each other. Values are strings because that
        # is what the source ids are compared as.
        for namespace, value in (row.get("external_ids") or {}).items():
            existing.external_ids = {
                **(existing.external_ids or {}),
                namespace: str(value),
            }

        # OSM supplies geometry only, and only to features that ARE points
        forms = (
            [row["name_default"], *existing.aliases] if row["feature_type"] in POINT_LIKE else []
        )
        for form in forms:
            candidate = osm.get(geo_key(form))
            if candidate:
                existing.geom = f"SRID=4326;POINT({candidate['lon']} {candidate['lat']})"
                existing.geom_verified = False
                existing.external_ids = {
                    **(existing.external_ids or {}),
                    "osm": candidate["osm_id"],
                }
                # Elevation is geometry, so OSM may supply it — but only where
                # the curated file is silent, which is the rule for everything
                # else here. Twelve of nineteen huts had no altitude at all,
                # and altitude is the physical check that stops a name match
                # attaching one building's facts to another; without it those
                # twelve rested on the name alone.
                if existing.alt_min is None and existing.alt_max is None:
                    existing.alt_max = metres(candidate.get("ele"))
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
