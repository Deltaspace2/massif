"""Fetch the Mont Blanc massif boundary from OSM and store it as WKT.

    python -m massif.scripts.fetch_massif_boundary > seeds/massif_boundary.wkt

The hut importer used a radius from the summit, because "the massif" had no
boundary in anything we held. A circle is a poor massif: at 12 km it cut off
Flégère, Dalmazzi, Elena and Lac Blanc; widening it to 17 swept in the
Beaufortain and the Fiz, which then had to be excluded by name.

OSM relation 7465762 "Massif du Mont-Blanc" (place=region, boundary=natural,
wikidata Q671343) is a real closed ring — 59 ways, 3758 points, about 630 km2.
It does the coarse work far better than a circle, and it is somebody's
published definition rather than ours.

It does NOT decide everything, and the importer still keeps two short lists:

  - It draws the high massif tightly, so the valley-floor huts on the Italian
    flank fall outside it — Bertone, Bonatti, Elena, Maison Vieille — and those
    are huts people mean when they say Mont Blanc. So does the Aiguilles Rouges
    side, Flégère and Lac Blanc, which Steven asked for by name.
  - "Le Refuge des Aiglons", a hotel in Chamonix town, is inside it.

A boundary answers "is this in the mountain group". It cannot answer "is this a
mountain hut", and it does not know which huts people associate with the range.
"""

from __future__ import annotations

import sys
import time

import httpx
from shapely.geometry import LineString
from shapely.ops import linemerge, polygonize, unary_union

OVERPASS = "https://overpass-api.de/api/interpreter"
RELATION = 7465762


def main() -> int:
    query = f"[out:json][timeout:180];rel({RELATION});out geom;"
    for attempt in range(4):
        response = httpx.post(
            OVERPASS,
            data={"data": query},
            timeout=240,
            headers={"User-Agent": "massif/0.1 boundary fetch (+https://github.com/Deltaspace2/massif)"},
        )
        if response.status_code == 200 and response.text.lstrip().startswith("{"):
            break
        print(f"attempt {attempt + 1}: HTTP {response.status_code}", file=sys.stderr)
        time.sleep(12)
    else:
        print("overpass unreachable", file=sys.stderr)
        return 1

    relation = response.json()["elements"][0]
    lines = [
        LineString([(p["lon"], p["lat"]) for p in member["geometry"]])
        for member in relation["members"]
        if len(member.get("geometry", [])) > 1
    ]
    polygons = list(polygonize(linemerge(unary_union(lines))))
    if not polygons:
        # An unclosed ring is not a boundary. Better to fail than to write a
        # shape that silently contains nothing.
        print("relation does not close into a polygon", file=sys.stderr)
        return 1

    boundary = max(polygons, key=lambda p: p.area)
    print(
        f"{relation['tags'].get('name')}: {len(lines)} ways, "
        f"bounds {tuple(round(b, 3) for b in boundary.bounds)}",
        file=sys.stderr,
    )
    print(boundary.wkt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
