"""Find geometry for the routes and couloirs. RECON FIRST.

Routes were seeded deliberately without coordinates — inventing sixty
coordinate pairs from memory is how you get a map that is confidently wrong.
So they exist in the database and not on the map, which makes the most
valuable features invisible on the thing that is supposed to be a map.

Three possible sources, and this script exists to find out which applies:

1. OSM ways/relations named for the route. Best case: real surveyed geometry.
   Alpine routes are patchily mapped — approach paths often exist as
   highway=path, glacier and ridge sections usually do not.
2. A hiking/alpine route relation covering it.
3. A schematic polyline through waypoints we already hold verified coordinates
   for (huts, peaks, lift stations). Honest if labelled as schematic; it puts
   the route roughly where it is without pretending to be a GPX track.

    python -m massif.scripts.fetch_route_geometry --probe
"""

from __future__ import annotations

import sys
import time

import httpx
from sqlalchemy import select

from massif.db import session_scope
from massif.models import Feature

OVERPASS = "https://overpass-api.de/api/interpreter"
BBOX = "45.72,6.60,46.05,7.10"


def _query(pattern: str) -> list[dict]:
    query = f"""
    [out:json][timeout:120];
    (
      way["name"~"{pattern}",i]({BBOX});
      relation["name"~"{pattern}",i]({BBOX});
    );
    out geom tags;
    """
    for attempt in range(3):
        try:
            response = httpx.post(
                OVERPASS, data={"data": query}, timeout=180,
                headers={"User-Agent": "massif/0.1 route geometry recon"},
            )
            response.raise_for_status()
            return response.json().get("elements", [])
        except Exception as exc:
            print(f"      overpass attempt {attempt + 1}: {type(exc).__name__}", file=sys.stderr)
            time.sleep(8 * (attempt + 1))
    return []


def _probe() -> int:
    with session_scope() as session:
        targets = session.scalars(
            select(Feature)
            .where(Feature.feature_type.in_(("route", "couloir")))
            .order_by(Feature.slug)
        ).all()
        targets = [
            (f.slug, f.name_default, list(f.aliases or []), f.geom is not None)
            for f in targets
        ]

    print(f"{len(targets)} routes and couloirs in the database\n")

    found_any = 0
    for slug, name, aliases, has_geom in targets:
        # a couple of distinctive words per route; OSM rarely uses our exact
        # phrasing, so search on the parts most likely to appear in a name
        terms = {name, *aliases}
        pattern = "|".join(
            sorted({t.split("(")[0].strip() for t in terms if len(t) > 4})[:6]
        ).replace(" ", ".")
        if not pattern:
            continue

        print(f"--- {slug}{'  (already has geometry)' if has_geom else ''}")
        elements = _query(pattern)
        lines = [e for e in elements if e.get("type") in ("way", "relation")]
        if not lines:
            print("      nothing in OSM under those names")
            continue

        found_any += 1
        for element in lines[:5]:
            tags = element.get("tags", {})
            geometry = element.get("geometry") or []
            print(
                f"      {element['type']}/{element['id']}  "
                f"{tags.get('name', '?')[:44]!r}  "
                f"{len(geometry)} nodes  "
                f"highway={tags.get('highway')} route={tags.get('route')}"
            )
        time.sleep(2)

    print(f"\n{found_any}/{len(targets)} had something in OSM")
    print("Where OSM has nothing, the fallback is a schematic polyline through")
    print("waypoints we already hold — labelled as schematic, never as a track.")
    return 0


if __name__ == "__main__":
    if "--probe" in sys.argv:
        raise SystemExit(_probe())
    print(__doc__)
