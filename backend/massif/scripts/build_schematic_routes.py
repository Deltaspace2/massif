"""Draw the routes nobody publishes a line for, through waypoints we already hold.

    python -m massif.scripts.build_schematic_routes            # dry run
    python -m massif.scripts.build_schematic_routes --apply

THE LAST RESORT, and only after the other two were tried and failed. Six routes
have no line anywhere we can reach: camptocamp holds a marker and no
`geom_detail` for four of them, splits the Goûter route across documents that
stop at 3840 m, and OSM's matches are decoys of the kind this project keeps
meeting — 'Impasse du Gouter' is a residential street in the valley and
'Dent du Geant' is a `highway=tertiary`, while the three "Goûter" ways are
refuge BUILDING outlines.

`fetch_route_geometry`'s docstring has allowed this fallback from the start,
always with the same condition attached:

    "a schematic polyline through waypoints we already hold verified
     coordinates for (huts, peaks, lift stations). Honest if labelled as
     schematic; it puts the route roughly where it is without pretending to be
     a GPX track."

So: **every vertex is a position we already hold**, never a coordinate typed
from memory — either one of our own features or an OSM peak node from
`seeds/osm_candidates.yaml`. Inventing sixty coordinate pairs is how you get a
map that is confidently wrong, and it is the thing the route work was written
to avoid.

And every line is written `geom_source = 'schematic'`, which the map draws
dashed and the feature page names in words. A schematic that renders
identically to a surveyed line is worse than no line at all, because the reader
cannot tell which they are looking at. If the rendering is ever removed, remove
this too.

The waypoint lists live in `seeds/features_curated.yaml` under `schematic_via`,
not in this file: they are curated data a person should be able to argue with,
and a climber reading that YAML can see the route being claimed.
"""

from __future__ import annotations

import sys

import yaml
from geoalchemy2.functions import ST_Centroid, ST_X, ST_Y
from sqlalchemy import select

from massif.db import session_scope
from massif.models import Feature
from massif.scripts.import_route_geometry import ELEVATION_TOLERANCE_M, MAX_SPAN_KM, in_massif
from massif.scripts.seed_features import load

# A schematic that needs three vertices to say anything is one thing; a
# "route" drawn as a single straight line across half the massif is another.
# Nothing we build should be longer than the longest real route we imported
# (the Vallée Blanche, 9.5 km) by much.
MAX_SCHEMATIC_KM = 12.0


def span_km(line: list[tuple[float, float]]) -> float:
    lons = [c[0] for c in line]
    lats = [c[1] for c in line]
    return (
        ((max(lats) - min(lats)) * 111.0) ** 2 + ((max(lons) - min(lons)) * 111.0 * 0.7) ** 2
    ) ** 0.5


def osm_peaks() -> dict[str, dict]:
    """Peak nodes with an elevation, by OSM id.

    From the same candidates file the huts were curated out of, so these are
    positions already in the repository rather than anything fetched here.
    """
    return {
        d["osm_id"]: d
        for d in load("osm_candidates.yaml")
        if d.get("feature_type") == "peak" and d.get("ele") and d.get("osm_id")
    }


def resolve(session, token: str, peaks: dict) -> tuple[tuple[float, float], float | None, str]:
    """One waypoint -> (lon, lat), elevation, and a label for the log.

    Raises rather than skipping. A schematic with a vertex silently dropped is
    a different route from the one the seed describes, and it would be drawn
    without anybody being told.
    """
    if token.startswith("osm:"):
        node = token[4:]
        peak = peaks.get(node)
        if peak is None:
            raise LookupError(f"{token} is not a peak with an elevation in osm_candidates.yaml")
        return (float(peak["lon"]), float(peak["lat"])), float(peak["ele"]), peak["name_default"]

    row = session.execute(
        select(Feature.name_default, ST_X(ST_Centroid(Feature.geom)), ST_Y(ST_Centroid(Feature.geom)))
        .where(Feature.slug == token)
    ).first()
    if row is None or row[1] is None:
        raise LookupError(f"{token} is not a feature we hold geometry for")
    name, lon, lat = row
    return (float(lon), float(lat)), None, name


def main(argv: list[str]) -> int:
    apply = "--apply" in argv
    curated = {
        row["slug"]: row for row in load("features_curated.yaml") if row.get("schematic_via")
    }
    if not curated:
        print("no route carries schematic_via", file=sys.stderr)
        return 0

    peaks = osm_peaks()
    built = refused = 0

    with session_scope() as session:
        for slug, row in sorted(curated.items()):
            feature = session.scalar(select(Feature).where(Feature.slug == slug))
            if feature is None:
                print(f"  ----  {slug:<26} not seeded")
                continue
            if feature.geom is not None and feature.geom_source != "schematic":
                # Never overwrite surveyed geometry with a drawing. If a real
                # line arrives for one of these later, that line wins and this
                # script must become a no-op for it rather than a regression.
                print(f"  ----  {slug:<26} already has {feature.geom_source} geometry — leaving it")
                continue

            try:
                points = [resolve(session, t, peaks) for t in row["schematic_via"]]
            except LookupError as exc:
                print(f"  XX    {slug:<26} {exc}")
                refused += 1
                continue

            line = [p[0] for p in points]
            if len(line) < 2:
                print(f"  XX    {slug:<26} needs at least two waypoints")
                refused += 1
                continue

            # The same guards the real importer applies. A line we drew is not
            # more trustworthy than one we fetched — if anything less, because
            # nobody surveyed it.
            top = max((e for _p, e, _n in points if e is not None), default=None)
            if feature.alt_max and top and abs(int(top) - feature.alt_max) > ELEVATION_TOLERANCE_M:
                print(
                    f"  XX    {slug:<26} waypoints top out at {top:.0f}m, "
                    f"we hold {feature.alt_max}m — refusing"
                )
                refused += 1
                continue

            length = span_km(line)
            limit = MAX_SPAN_KM.get(str(feature.feature_type), MAX_SCHEMATIC_KM)
            if length > limit:
                print(
                    f"  XX    {slug:<26} spans {length:.1f} km, too long for a "
                    f"{feature.feature_type} — refusing"
                )
                refused += 1
                continue

            if not in_massif(line):
                print(f"  XX    {slug:<26} leaves the massif — refusing")
                refused += 1
                continue

            print(f"  OK    {slug:<26} {len(line)} waypoints, {length:.1f} km, top {top or '?'}m")
            for (lon, lat), ele, name in points:
                print(f"          {name[:38]:38} {lat:.5f},{lon:.5f}" + (f"  {ele:.0f}m" if ele else ""))

            if apply:
                wkt = "LINESTRING(" + ",".join(f"{lon} {lat}" for lon, lat in line) + ")"
                feature.geom = f"SRID=4326;{wkt}"
                feature.geom_source = "schematic"
                feature.geom_verified = False
            built += 1

        print(f"\n{built} drawn, {refused} refused")
        if not apply:
            print("dry run — nothing written; pass --apply")
            session.rollback()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
