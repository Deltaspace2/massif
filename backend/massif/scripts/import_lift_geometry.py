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
import re
import sys
import time
import unicodedata

import httpx
from sqlalchemy import select

from massif.db import session_scope
from massif.models import Feature
from massif.scripts.import_route_geometry import in_massif
from massif.scripts.seed_features import load

# Tried in order. The official instance first; the Mail.ru mirror is a
# long-running public instance and exists here because on 10 Sep 2026 the
# route to overpass-api.de (and to the Kumi mirror) was dead from this
# network while general connectivity was fine — errno 101, not a refusal.
OVERPASS_ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
)
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


def _ask(query: str) -> list[dict] | None:
    """One Overpass question, against whichever endpoint answers."""
    for endpoint in OVERPASS_ENDPOINTS:
        for attempt in range(2):
            try:
                response = httpx.post(endpoint, data={"data": query}, headers=UA, timeout=180)
                response.raise_for_status()
                return response.json().get("elements", [])
            except Exception as exc:
                print(
                    f"      {endpoint.split('/')[2]}: attempt {attempt + 1}: "
                    f"{type(exc).__name__}",
                    file=sys.stderr,
                )
                time.sleep(4 * (attempt + 1))
    return None


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
        got = _ask(query)
        if got is None:
            print(f"      {oid}: all endpoints failed", file=sys.stderr)
        else:
            elements.extend(got)
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


# The operator writes "TPH AIGUILLE DU MIDI"; OSM writes "TPH Aiguille du
# Midi" or just "Planpraz". Strip accents, the lift-type prefixes both sides
# use, and French articles, and the two vocabularies meet in the middle.
_STOPWORDS = re.compile(
    r"\b(tph|tc|tcd|tsd|ts|tk|funi|telepherique|telecabine|telesiege|teleski|"
    r"du|de|des|le|la|les|d)\b"
)


def machine_key(name: str) -> str:
    flat = "".join(
        c for c in unicodedata.normalize("NFD", name or "") if unicodedata.category(c) != "Mn"
    ).lower()
    return " ".join(_STOPWORDS.sub(" ", flat).split())


def match_machines(lifts, aerialways: list[dict]) -> dict[str, list[str]]:
    """slug -> OSM way ids, for tracked machines with no geometry.

    EXACT normalised-name equality, within the massif bbox the aerialways were
    fetched from — never a fuzzy score. Rule 8 says a name score cannot tell
    you which mountain something is on, and the route import proved it; what
    makes equality safe here is that the candidate set is only the lifts of
    this massif, and their names ("Planpraz", "Charamillon", "Autannes") are
    distinctive within it.

    A trailing number is the one forgiveness: "La Breya 1" and "La Breya 2"
    are both the thing our `la-breya` sector means, so a machine may match
    several ways and become a MultiLineString.
    """
    out: dict[str, list[str]] = {}
    for lift in lifts:
        if lift.geom is not None:
            continue
        key = machine_key(lift.name_default)
        if not key:
            continue
        hits = [
            a["id"]
            for a in aerialways
            if machine_key(a["name"]) == key
            or machine_key(a["name"]).rstrip("0123456789 ") == key
        ]
        if hits:
            out[lift.slug] = hits
    return out


def fetch_aerialways() -> list[dict]:
    """Every NAMED aerialway way in the massif bbox, with its line geometry.

    All kinds, not `cable_car|gondola` — that narrow filter is the recorded
    four-time "not in OSM meant we never asked" bug, and measured properly the
    bbox holds 287 aerialway ways of which the old filter saw 45.
    """
    got = _ask(
        '[out:json][timeout:150];way["aerialway"]["name"](45.72,6.60,46.05,7.10);out geom;'
    )
    if got is None:
        return []
    out = []
    for element in got:
        points = [(p["lon"], p["lat"]) for p in element.get("geometry") or []]
        if len(points) >= 2:
            out.append(
                {"id": f"way/{element['id']}", "name": element["tags"].get("name"), "line": points}
            )
    return out


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

        # ---- phase 2: the tracked machines. The operator feed creates them
        # with no geometry by design; their lines exist in OSM under names a
        # strict normaliser can meet.
        aerialways = fetch_aerialways()
        print(f"\n{len(aerialways)} named aerialways in the bbox")
        matched = match_machines(lifts, aerialways)
        by_id = {a["id"]: a for a in aerialways}
        for slug, ids in sorted(matched.items()):
            lift = next(x for x in lifts if x.slug == slug)
            parts = [by_id[i]["line"] for i in ids]
            flat = [p for part in parts for p in part]
            length = span_km(parts)
            if not in_massif(flat):
                print(f"  XX    {slug:30} leaves the massif — refusing")
                refused += 1
                continue
            if length > 8.0:
                # No single cable in this massif is 8 km; a match that long is
                # a wrong match wearing the right name.
                print(f"  XX    {slug:30} spans {length:.1f} km — refusing")
                refused += 1
                continue
            names = ", ".join(by_id[i]["name"] for i in ids)
            print(f"  OK    {slug:30} {len(parts)} way(s), {length:>4.1f} km  <- {names[:40]}")
            if args.apply:
                lift.geom = f"SRID=4326;{wkt(parts)}"
                lift.geom_source = "osm"
                lift.geom_verified = False
                lift.external_ids = {**(lift.external_ids or {}), "osm_line": ",".join(ids)}
            drawn += 1

        print(f"\n{drawn} drawn, {refused} refused")
        if not args.apply:
            print("dry run — nothing written; pass --apply")
            session.rollback()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
