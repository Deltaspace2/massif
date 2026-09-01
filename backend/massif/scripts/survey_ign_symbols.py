"""Which of our huts does IGN's basemap already draw a symbol for?

    python -m massif.scripts.survey_ign_symbols          # report
    python -m massif.scripts.survey_ign_symbols --write  # regenerate the list

WHY. The map draws its own hut symbol so that every hut is visible. IGN draws
one too, from z13 — but only for SOME huts, and there is no rule for which. At
z15 it symbolises 29 of our 59: all five Swiss and 24 of 25 Italian huts get
nothing, and so do two French ones, while Rifugio Torino does get a glyph. It
is the French national mapper, and it shows.

Drawing ours on top of theirs puts two houses on one hut — their symbol is
offset from the point and uses the outline variant, so they do not merge, they
just look like two huts. Not drawing ours leaves 30 huts unmarked at exactly
the zoom where you go looking for them. Neither is acceptable, so the map needs
to know, per hut, whether IGN has it covered.

HOW. Fetch the tiles around each hut, crop a window on the hut's own pixel, and
count pixels of IGN's glyph green (#246138, sampled from their tiles). This is
the third method tried: counting "greenish" pixels in a single tile caught
vegetation and missed glyphs that sat in a neighbouring tile, and produced a
confident wrong answer from two huts that happened to agree.

The result is cartography, not domain data, so it is written to the frontend as
a generated constant rather than into the database. Re-run it if IGN changes
their symbology or we add huts.
"""

from __future__ import annotations

import argparse
import io
import math
from pathlib import Path

import httpx
from PIL import Image
from sqlalchemy import text

from massif.db import session_scope

URL = (
    "https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0"
    "&LAYER=GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2&STYLE=normal&TILEMATRIXSET=PM"
    "&TILEMATRIX={z}&TILECOL={x}&TILEROW={y}&FORMAT=image/png"
)
TILE = 256
# z13 is where their glyph appears — measured on the Goûter, the Cosmiques and
# Torino: nothing at z11 or z12, present from z13 on all three. Surveyed at 15
# because the symbol is drawn further from the point as you zoom in, and 15 is
# comfortably clear of the transition.
SURVEY_ZOOM = 15
WINDOW = 30
GLYPH = (0x24, 0x61, 0x38)
TOLERANCE = 20

OUT = Path(__file__).resolve().parents[3] / "frontend" / "components" / "ignSymbolised.ts"


def _tile(client: httpx.Client, x: int, y: int, cache: dict) -> Image.Image | None:
    if (x, y) not in cache:
        response = client.get(URL.format(z=SURVEY_ZOOM, x=x, y=y), timeout=60)
        cache[(x, y)] = (
            Image.open(io.BytesIO(response.content)).convert("RGB")
            if response.status_code == 200
            else None
        )
    return cache[(x, y)]


def glyph_pixels(client: httpx.Client, lat: float, lon: float, cache: dict) -> int:
    n = 2**SURVEY_ZOOM
    fx = (lon + 180) / 360 * n
    fy = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
    tx, ty = int(fx), int(fy)
    px, py = (fx - tx) * TILE, (fy - ty) * TILE

    total = 0
    for gx in (tx - 1, tx, tx + 1):
        for gy in (ty - 1, ty, ty + 1):
            image = _tile(client, gx, gy, cache)
            if image is None:
                continue
            ox, oy = (gx - tx) * TILE, (gy - ty) * TILE
            left, top = int(px - WINDOW - ox), int(py - WINDOW - oy)
            x0, y0 = max(0, left), max(0, top)
            x1, y1 = min(TILE, left + 2 * WINDOW), min(TILE, top + 2 * WINDOW)
            if x1 <= x0 or y1 <= y0:
                continue
            for pixel in image.crop((x0, y0, x1, y1)).get_flattened_data():
                if all(abs(pixel[i] - GLYPH[i]) < TOLERANCE for i in range(3)):
                    total += 1
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="regenerate the TS constant")
    args = parser.parse_args()

    with session_scope() as session:
        huts = session.execute(
            text(
                "SELECT slug, country, ST_Y(geom::geometry) lat, ST_X(geom::geometry) lon "
                "FROM features WHERE feature_type='hut' AND geom IS NOT NULL ORDER BY slug"
            )
        ).all()

    cache: dict = {}
    drawn: list[str] = []
    with httpx.Client(
        headers={"User-Agent": "massif/0.1 hut symbology survey (+https://github.com/Deltaspace2/massif)"}
    ) as client:
        for hut in huts:
            found = glyph_pixels(client, hut.lat, hut.lon, cache)
            if found:
                drawn.append(hut.slug)
            print(f"  {'IGN' if found else '  —'}  {hut.country} {hut.slug}")

    print(f"\nIGN symbolises {len(drawn)} of {len(huts)} huts at z{SURVEY_ZOOM}")
    if not args.write:
        print("report only — pass --write to regenerate the frontend constant")
        return 0

    body = ",\n".join(f'  "{slug}"' for slug in sorted(drawn))
    OUT.write_text(
        "// GENERATED by massif.scripts.survey_ign_symbols — do not edit by hand.\n"
        "//\n"
        "// Huts IGN's basemap already draws a symbol for, from z13. The map\n"
        "// suppresses its own house for these at that zoom and above, so their\n"
        "// cartography is not competing with a second one; every other hut keeps\n"
        f"// ours, because IGN draws nothing there at any zoom.\n"
        f"//\n// {len(drawn)} of {len(huts)} huts, surveyed at z{SURVEY_ZOOM}.\n"
        "export const IGN_SYMBOLISED: ReadonlySet<string> = new Set([\n"
        f"{body},\n]);\n",
        encoding="utf-8",
    )
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
