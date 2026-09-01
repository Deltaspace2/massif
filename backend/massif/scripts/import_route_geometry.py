"""Import route geometry from camptocamp.org, bounded to the massif.

OSM maps approach paths and little above the snowline. camptocamp is where
climbers document routes, and its documents carry geom_detail — a real
LineString, not a marker.

WHY THIS FETCHES BY BOUNDING BOX AND NOT BY NAME. c2c's search is global and
unranked by distance. Searching our route names returned, as the top hit:

    Goûter Route    -> "Voie Royale du Gäntrisch"    (Bern, 100 km away)
                    -> "Kungsleden"                   (Sweden)
    Trois Monts     -> "Les Trois Monts"              (Basque country)
    Grand Couloir   -> "le grand Couloir-Malaval"     (Vanoise, 50 km south)
    Arête du Diable ->                                (Provence)

Taking the first result would have drawn the normal route up Mont Blanc across
the Bernese Oberland. Fetching by bbox makes "a route called X" mean "a route
called X in this massif", and every imported line is then checked to fall
inside the box anyway — a cheap assertion that rejects all of the above.

Coordinates arrive as EPSG:3857 metres and are reprojected to 4326.

    python -m massif.scripts.import_route_geometry            # dry run
    python -m massif.scripts.import_route_geometry --apply
"""

from __future__ import annotations

import json
import math
import sys
import time

import httpx
from rapidfuzz import fuzz, process
from sqlalchemy import select

from massif.db import session_scope
from massif.ingest.fr_dates import strip_accents
from massif.models import Feature

API = "https://api.camptocamp.org"
UA = {"User-Agent": "massif/0.1 (+route geometry import)"}

# Mont Blanc massif, WGS84: south, west, north, east
BBOX_WGS = (45.72, 6.60, 46.05, 7.10)
# A line may stray slightly outside the seed box; a line in another country
# may not.
TOLERANCE_DEG = 0.15

# Only applied within the massif candidate set. High enough that "Vallée
# Blanche" reaches "Vraie Vallée Blanche" without reaching a neighbouring
# route on the same face.
FUZZY_FLOOR = 84.0

# A name score cannot tell you which mountain a route is on. Altitude can.
# Live rejections this caught, both scoring 95+ on the name:
#   gouter-route  -> "Voie normale", max 2965 m, 20 km north (we hold 4808)
#   grand-couloir -> "Grand couloir W", max 3096 m over 12.7 km (the Buet)
# Both would have drawn a confident line up the wrong mountain.
ELEVATION_TOLERANCE_M = 250

# A couloir is a feature you cross, not a valley you walk down. Anything this
# long under that type is a different thing wearing a similar name.
MAX_SPAN_KM = {"couloir": 3.0}


def to_3857(lon: float, lat: float) -> tuple[float, float]:
    x = lon * 20037508.34 / 180.0
    y = math.log(math.tan((90.0 + lat) * math.pi / 360.0)) / (math.pi / 180.0)
    return x, y * 20037508.34 / 180.0


def to_wgs84(x: float, y: float) -> tuple[float, float]:
    lon = x / 20037508.34 * 180.0
    lat = y / 20037508.34 * 180.0
    lat = 180.0 / math.pi * (2.0 * math.atan(math.exp(lat * math.pi / 180.0)) - math.pi / 2.0)
    return lon, lat


def key(text: str) -> str:
    """Comparison key: accents and case folded, punctuation dropped. NOT the
    resolver's normalise(), which strips 'voie', 'arête' and 'couloir' and
    would happily equate a route with its hut."""
    text = strip_accents(text or "").casefold()
    return " ".join("".join(c if c.isalnum() else " " for c in text).split())


def in_massif(coords: list[tuple[float, float]]) -> bool:
    south, west, north, east = BBOX_WGS
    for lon, lat in coords:
        if not (west - TOLERANCE_DEG <= lon <= east + TOLERANCE_DEG):
            return False
        if not (south - TOLERANCE_DEG <= lat <= north + TOLERANCE_DEG):
            return False
    return True


def fetch_massif_routes() -> list[dict]:
    """Every c2c route document whose marker sits in the massif."""
    south, west, north, east = BBOX_WGS
    x1, y1 = to_3857(west, south)
    x2, y2 = to_3857(east, north)
    bbox = f"{int(x1)},{int(y1)},{int(x2)},{int(y2)}"

    routes: list[dict] = []
    offset = 0
    while True:
        try:
            response = httpx.get(
                f"{API}/routes",
                params={"bbox": bbox, "limit": 100, "offset": offset},
                headers=UA,
                timeout=60,
            )
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            print(f"  fetch failed at offset {offset}: {type(exc).__name__}: {exc}")
            break

        documents = data.get("documents") or []
        routes.extend(documents)
        total = data.get("total", 0)
        print(f"  fetched {len(routes)}/{total}")
        offset += 100
        if offset >= total or not documents:
            break
        time.sleep(1)
    return routes


def titles(document: dict) -> list[str]:
    out = []
    for locale in document.get("locales") or []:
        for field in ("title", "title_prefix"):
            value = locale.get(field)
            if value:
                out.append(value)
    return out


def line_from(detail: dict) -> list[tuple[float, float]] | None:
    geometry = detail.get("geometry") or {}
    raw = geometry.get("geom_detail")
    if not raw:
        return None
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return None

    kind = parsed.get("type")
    coords = parsed.get("coordinates") or []
    if kind == "LineString":
        parts = [coords]
    elif kind == "MultiLineString":
        parts = coords
    else:
        return None

    longest = max(parts, key=len) if parts else []
    return [to_wgs84(p[0], p[1]) for p in longest if len(p) >= 2] or None


def main(argv: list[str]) -> int:
    apply = "--apply" in argv

    print("Fetching c2c routes inside the massif bbox ...")
    documents = fetch_massif_routes()
    print(f"{len(documents)} route documents in the massif\n")

    index: dict[str, dict] = {}
    for document in documents:
        for title in titles(document):
            index.setdefault(key(title), document)

    with session_scope() as session:
        targets = session.scalars(
            select(Feature)
            .where(Feature.feature_type.in_(("route", "couloir")))
            .order_by(Feature.slug)
        ).all()

        matched = skipped = rejected = 0
        for feature in targets:
            names = [feature.name_default, *(feature.aliases or [])]

            document = next((index[key(n)] for n in names if key(n) in index), None)
            score = 100.0
            title = None

            if document is None:
                # Fuzzy is SAFE here and was not before. The candidate set is
                # already every c2c route inside the massif bbox, so the worst
                # a loose match can do is pick the wrong route on the right
                # mountain — not the Gäntrisch, not Sweden. c2c names routes
                # its own way ("Via delle Aguilles Grises - Via del Papa",
                # "Vraie Vallée Blanche"), which exact matching cannot reach.
                best = None
                for name in names:
                    hit = process.extractOne(key(name), list(index), scorer=fuzz.WRatio)
                    if hit and (best is None or hit[1] > best[1]):
                        best = hit
                if best and best[1] >= FUZZY_FLOOR:
                    document, score = index[best[0]], best[1]

            if document is None:
                print(f"  ----  {feature.slug:<26} no c2c route of that name here")
                skipped += 1
                continue

            title = (titles(document) or ["?"])[0]

            try:
                detail = httpx.get(
                    f"{API}/routes/{document['document_id']}", headers=UA, timeout=45
                ).json()
            except Exception as exc:
                print(f"  ----  {feature.slug:<26} detail failed: {type(exc).__name__}")
                skipped += 1
                continue
            time.sleep(1)

            line = line_from(detail)
            if not line or len(line) < 2:
                print(f"  ----  {feature.slug:<26} no geom_detail (marker only)")
                skipped += 1
                continue

            # Enough evidence to judge the match, because a score cannot.
            # score cannot. "Voie normale" is the title of a route on every
            # peak in the massif, and "Grand couloir W" could as easily be the
            # Buet as the Goûter — both inside the bbox, so geography does not
            # separate them. Endpoints and length do.
            lons = [c[0] for c in line]
            lats = [c[1] for c in line]
            span_km = (
                ((max(lats) - min(lats)) * 111.0) ** 2
                + ((max(lons) - min(lons)) * 111.0 * 0.7) ** 2
            ) ** 0.5
            elevation = detail.get("elevation_max")

            # --- altitude check: does this document belong to our mountain?
            if feature.alt_max and elevation:
                gap = abs(int(elevation) - feature.alt_max)
                if gap > ELEVATION_TOLERANCE_M:
                    print(
                        f"  XX    {feature.slug:<26} tops out at {elevation}m, "
                        f"we hold {feature.alt_max}m ({gap}m apart) — refusing"
                    )
                    print(f"          would have been: {title[:60]!r}")
                    rejected += 1
                    continue

            # --- span check: is this the right SHAPE of thing?
            limit = MAX_SPAN_KM.get(str(feature.feature_type))
            if limit and span_km > limit:
                print(
                    f"  XX    {feature.slug:<26} spans {span_km:.1f} km, "
                    f"too long for a {feature.feature_type} — refusing"
                )
                print(f"          would have been: {title[:60]!r}")
                rejected += 1
                continue

            if not in_massif(line):
                # The safety net. Rejects the Gäntrisch, Sweden and the Vanoise.
                print(
                    f"  XX    {feature.slug:<26} line falls outside the massif "
                    f"— refusing ({line[0][1]:.3f}, {line[0][0]:.3f})"
                )
                rejected += 1
                continue

            wkt = "LINESTRING(" + ",".join(f"{lon} {lat}" for lon, lat in line) + ")"

            flag = "" if score >= 99 else f"  ~{score:.0f}"
            print(
                f"  OK    {feature.slug:<26} {len(line):>4} points  "
                f"c2c/{document['document_id']}{flag}"
            )
            # print what it matched, always: a name we did not choose is the
            # thing most worth a human glancing at
            print(f"          matched: {title[:66]!r}")
            print(
                f"          {span_km:.1f} km span, max {elevation}m, "
                f"{line[0][1]:.4f},{line[0][0]:.4f} -> "
                f"{line[-1][1]:.4f},{line[-1][0]:.4f}"
            )
            if apply:
                feature.geom = f"SRID=4326;{wkt}"
                feature.geom_verified = False
                feature.external_ids = {
                    **(feature.external_ids or {}),
                    "camptocamp": str(document["document_id"]),
                }
            matched += 1

        if not apply:
            session.rollback()

    print(
        f"\n{matched} matched, {skipped} without geometry, {rejected} refused "
        f"(wrong mountain, wrong shape, or outside the massif)"
    )
    print("dry run — nothing written; pass --apply" if not apply else "written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
