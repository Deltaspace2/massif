"""camptocamp.org as a route-geometry source. RECON.

OSM maps approach paths and almost nothing above the snowline: of thirteen
routes and couloirs, it had real geometry for three. Nobody surveys a line up
a moving glacier — but climbers document routes, and camptocamp.org is where
they do it. Public API, no key.

Two things to establish:

1. Which of our routes exist there, and under what document_id.
2. Whether the detail endpoint returns `geom_detail` — a LineString — or only
   `geom`, a single Point marker. The list endpoint gives Points, which would
   be no better than what we have.

Coordinates come back as **EPSG:3857 (Web Mercator)** in metres, not lat/lon
and not Swiss LV95. They need reprojecting to 4326 before they touch PostGIS.

    python -m massif.scripts.probe_camptocamp --probe
"""

from __future__ import annotations

import json
import math
import sys
import time

import httpx
from sqlalchemy import select

from massif.db import session_scope
from massif.models import Feature

API = "https://api.camptocamp.org"
UA = {"User-Agent": "massif/0.1 route geometry recon"}


def to_wgs84(x: float, y: float) -> tuple[float, float]:
    """EPSG:3857 metres -> (lon, lat)."""
    lon = x / 20037508.34 * 180.0
    lat = y / 20037508.34 * 180.0
    lat = 180.0 / math.pi * (2.0 * math.atan(math.exp(lat * math.pi / 180.0)) - math.pi / 2.0)
    return round(lon, 6), round(lat, 6)


def _get(path: str, **params):
    try:
        response = httpx.get(f"{API}{path}", params=params, headers=UA, timeout=45)
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        print(f"      {type(exc).__name__}: {exc}")
        return None


def _probe() -> int:
    with session_scope() as session:
        targets = [
            (f.slug, f.name_default, list(f.aliases or []))
            for f in session.scalars(
                select(Feature)
                .where(Feature.feature_type.in_(("route", "couloir")))
                .order_by(Feature.slug)
            )
        ]

    for slug, name, aliases in targets:
        print(f"\n--- {slug}  ({name})")
        # search route documents only: t=r
        data = _get("/search", q=name, t="r", limit=5)
        routes = ((data or {}).get("routes") or {}).get("documents") or []
        if not routes and aliases:
            data = _get("/search", q=aliases[0], t="r", limit=5)
            routes = ((data or {}).get("routes") or {}).get("documents") or []

        if not routes:
            print("      no route documents found")
            time.sleep(1)
            continue

        for doc in routes[:3]:
            locales = doc.get("locales") or [{}]
            title = locales[0].get("title", "?")
            print(f"      {doc['document_id']:>8}  {title[:56]!r}  "
                  f"{doc.get('elevation_max')}m")

        # look at the best match in detail — is there a LineString?
        best = routes[0]["document_id"]
        detail = _get(f"/routes/{best}")
        if detail:
            geometry = detail.get("geometry") or {}
            for key in ("geom", "geom_detail"):
                raw = geometry.get(key)
                if not raw:
                    print(f"      {key}: absent")
                    continue
                try:
                    parsed = json.loads(raw) if isinstance(raw, str) else raw
                except Exception:
                    print(f"      {key}: unparseable")
                    continue
                kind = parsed.get("type")
                coords = parsed.get("coordinates") or []
                count = len(coords) if kind != "Point" else 1
                print(f"      {key}: {kind}, {count} points")
                if kind == "Point":
                    print(f"        -> {to_wgs84(*coords)}")
                elif coords:
                    flat = coords[0] if isinstance(coords[0][0], list) else coords
                    print(f"        first -> {to_wgs84(*flat[0][:2])}")
                    print(f"        last  -> {to_wgs84(*flat[-1][:2])}")
        time.sleep(1)

    print("\nA LineString in geom_detail is what we want. A Point in geom only")
    print("is no better than what we already have, and the fallback is a")
    print("schematic polyline through waypoints we hold — labelled as such.")
    return 0


if __name__ == "__main__":
    if "--probe" in sys.argv:
        raise SystemExit(_probe())
    print(__doc__)
