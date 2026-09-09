"""Draw the lifts and railways as the lines they are, not as dots.

    python -m massif.scripts.import_lift_geometry            # dry run
    python -m massif.scripts.import_lift_geometry --apply

Measured 10 Sep 2026: of forty lifts, fourteen had geometry and **every one of
them was a Point** — nine of those stored against an OSM `way/`, which is to
say we held the id of a line and drew a dot in the middle of it. A cable car is
a cable between two stations and a railway is a railway; neither is a place.

That is also the whole of "some lifts are marked, some have a line, some are
just a green dot": the map was rendering faithfully, and what it was given was
wrong.

TWO KINDS OF THING, and the difference matters:

  aerialways   one OSM way IS the whole cable. Brévent is 3 points, the
               Flégère gondola 13, Prarion 17. Take the way.

  railways     one way is a SEGMENT. `way/25513422`, the id we held for the
               Mont-Blanc Express, is two points of a line the task list
               described as 112 segments — which is exactly why that railway
               rendered as a dot near Les Houches. The whole line only exists
               as a relation, and only as the INFRASTRUCTURE relation
               (`route=railway`): the four others carrying that name are
               directional services, two SNCF and two TMR, and a timetable is
               not a shape. Those relations are pinned by hand in
               `features_curated.yaml` under `osm_line`, never searched for.

MULTILINESTRING, not a stitched LineString. A relation's members arrive as
separate ways and joining them needs their order and orientation resolved;
getting that subtly wrong draws a railway that doubles back through a village.
Keeping them separate is honest about what OSM holds, and the map already reads
MultiLineString — `isLine()` has always accepted it.

Every line is checked against the massif box before it is written, the same
guard the route import uses, because an id typed wrong is the failure this
project keeps meeting.
"""

from __future__ import annotations

import argparse
import sys
import time

import httpx
from sqlalchemy import select

from massif.db import session_scope
from massif.models import Feature
from massif.scripts.import_route_geometry import in_massif
from massif.scripts.seed_features import load

OVERPASS = "https://overpass-api.de/api/interpreter"
UA = {"User-Agent": "massif/0.1 (+https://montblancmassif.org/about; steven@innes.io)"}

# The massif is about 35 km across. Anything longer than this is not a lift in
# it, whatever its id says.
MAX_KM = 45.0


def span_km(parts: list[list[tuple[float, float]]]) -> float:
    flat = [p for part in parts for p in part]
    lons = [c[0] for c in flat]
    lats = [c[1] for c in flat]
    return (
        ((max(lats) - min(lats)) * 111.0) ** 2 + ((max(lons) - min(lons)) * 111.0 * 0.7) ** 2
    ) ** 0.5


def pinned_lines() -> dict[str, str]:
    """slug -> OSM id, for the railways whose line is a relation."""
    return {
        row["slug"]: row["osm_line"] for row in load("features_curated.yaml") if row.get("osm_line")
    }


def fetch_geometry(osm_ids: list[str]) -> dict[str, list[list[tuple[float, float]]]]:
    """OSM id -> its parts, each a list of (lon, lat).

    A way has one part. A relation has one per member way, which is what makes
    the result a MultiLineString rather than a guess at their order.
    """
    out: dict[str, list[list[tuple[float, float]]]] = {}
    elements: list[dict] = []
    # ONE REQUEST PER OBJECT, with a pause. Asked for all eleven at once,
    # Overpass answers 504: a relation with `out geom` pulls every member's
    # points, and the Mont-Blanc Express alone is 112 segments. Eleven small
    # questions also sit better with "rate-limit hard, we are guests on these
    # servers" than one that times their server out.
    for oid in osm_ids:
        kind, _, num = oid.partition("/")
        if kind not in ("way", "relation") or not num.isdigit():
            continue
        query = f"[out:json][timeout:120];{kind}({num});out geom;"
        for attempt in range(3):
            try:
                response = httpx.post(OVERPASS, data={"data": query}, headers=UA, timeout=180)
                response.raise_for_status()
                elements.extend(response.json().get("elements", []))
                break
            except Exception as exc:
                print(f"      {oid}: attempt {attempt + 1}: {type(exc).__name__}", file=sys.stderr)
                time.sleep(5 * (attempt + 1))
        time.sleep(2)

    for element in elements:
        key = f"{element['type']}/{element['id']}"
        if element["type"] == "way":
            points = [(p["lon"], p["lat"]) for p in element.get("geometry") or []]
            if len(points) >= 2:
                out[key] = [points]
        elif element["type"] == "relation":
            parts = []
            for member in element.get("members") or []:
                # Stops and platforms are nodes, and a station is not the line.
                points = [(p["lon"], p["lat"]) for p in member.get("geometry") or []]
                if len(points) >= 2:
                    parts.append(points)
            if parts:
                out[key] = parts
    return out


def wkt(parts: list[list[tuple[float, float]]]) -> str:
    if len(parts) == 1:
        inner = ",".join(f"{lon} {lat}" for lon, lat in parts[0])
        return f"LINESTRING({inner})"
    bodies = ",".join(
        "(" + ",".join(f"{lon} {lat}" for lon, lat in part) + ")" for part in parts
    )
    return f"MULTILINESTRING({bodies})"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write; otherwise dry run")
    args = parser.parse_args(argv)

    pins = pinned_lines()
    with session_scope() as session:
        lifts = session.scalars(
            select(Feature).where(Feature.feature_type == "lift").order_by(Feature.slug)
        ).all()

        wanted: dict[str, str] = {}
        for lift in lifts:
            # A pinned relation wins: for a railway the stored way is one
            # segment of the line, and a segment is worse than nothing.
            osm = pins.get(lift.slug) or (lift.external_ids or {}).get("osm")
            if osm and osm.split("/")[0] in ("way", "relation"):
                wanted[lift.slug] = osm

        print(f"{len(wanted)} lifts with a line to fetch, of {len(lifts)}")
        geometry = fetch_geometry(sorted(set(wanted.values())))

        drawn = refused = 0
        for lift in lifts:
            osm = wanted.get(lift.slug)
            if not osm:
                continue
            parts = geometry.get(osm)
            if not parts:
                print(f"  ----  {lift.slug:30} {osm} has no line geometry")
                continue
            length = span_km(parts)
            flat = [p for part in parts for p in part]
            if not in_massif(flat):
                print(f"  XX    {lift.slug:30} leaves the massif — refusing ({osm})")
                refused += 1
                continue
            if length > MAX_KM:
                print(f"  XX    {lift.slug:30} spans {length:.1f} km — refusing ({osm})")
                refused += 1
                continue
            kind = "relation" if osm.startswith("relation") else "way"
            print(
                f"  OK    {lift.slug:30} {len(parts):>3} part(s), "
                f"{sum(len(p) for p in parts):>4} points, {length:>5.1f} km  {kind}"
            )
            if args.apply:
                lift.geom = f"SRID=4326;{wkt(parts)}"
                lift.geom_source = "osm"
                lift.geom_verified = False
                lift.external_ids = {**(lift.external_ids or {}), "osm_line": osm}
            drawn += 1

        print(f"\n{drawn} drawn, {refused} refused")
        if not args.apply:
            print("dry run — nothing written; pass --apply")
            session.rollback()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
