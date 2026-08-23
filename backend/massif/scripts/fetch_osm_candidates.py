"""Generate feature candidates for the Mont Blanc massif from OpenStreetMap.

OSM is used for CANDIDATE GENERATION, not as the seed. It is good at where
things are and unreliable at what they are called; the curated YAML is the
reverse. This script produces coordinates for a human to curate, matched into
seeds/features_curated.yaml by alias at seed time.

Needs network. Run it on your own machine, not in a sandbox:

    python -m massif.scripts.fetch_osm_candidates > seeds/osm_candidates.yaml
"""

from __future__ import annotations

import sys
import time

import httpx
import yaml

OVERPASS = "https://overpass-api.de/api/interpreter"

# Mont Blanc massif bounding box: south, west, north, east
BBOX = (45.72, 6.60, 46.05, 7.10)

QUERY = f"""
[out:json][timeout:180];
(
  node["tourism"~"^(alpine_hut|wilderness_hut)$"]{BBOX};
  way["tourism"~"^(alpine_hut|wilderness_hut)$"]{BBOX};
  node["natural"="peak"]["ele"]{BBOX};
  way["aerialway"~"^(cable_car|gondola)$"]{BBOX};
  way["railway"="rail"]["usage"="tourism"]{BBOX};
  node["aerialway"="station"]{BBOX};
  way["natural"="glacier"]{BBOX};
  relation["natural"="glacier"]{BBOX};
);
out center tags;
"""

TYPE_MAP = {
    "alpine_hut": "hut",
    "wilderness_hut": "hut",
    "peak": "peak",
    "cable_car": "lift",
    "gondola": "lift",
    "station": "lift_station",
    "glacier": "glacier",
}


def classify(tags: dict) -> str | None:
    if tags.get("tourism") in ("alpine_hut", "wilderness_hut"):
        return "hut"
    if tags.get("natural") == "peak":
        return "peak"
    if tags.get("aerialway") in ("cable_car", "gondola"):
        return "lift"
    if tags.get("aerialway") == "station":
        return "lift_station"
    if tags.get("natural") == "glacier":
        return "glacier"
    if tags.get("railway") == "rail":
        return "lift"
    return None


def main() -> int:
    print("querying overpass ...", file=sys.stderr)
    for attempt in range(3):
        try:
            response = httpx.post(
                OVERPASS,
                data={"data": QUERY},
                timeout=240,
                headers={"User-Agent": "massif/0.1 seed script"},
            )
            response.raise_for_status()
            break
        except Exception as exc:  # overpass is frequently busy
            print(f"attempt {attempt + 1} failed: {exc}", file=sys.stderr)
            time.sleep(10 * (attempt + 1))
    else:
        print("overpass unreachable", file=sys.stderr)
        return 1

    elements = response.json().get("elements", [])
    out = []
    for el in elements:
        tags = el.get("tags", {})
        name = tags.get("name")
        if not name:
            continue
        kind = classify(tags)
        if kind is None:
            continue

        lat = el.get("lat") or (el.get("center") or {}).get("lat")
        lon = el.get("lon") or (el.get("center") or {}).get("lon")
        if lat is None or lon is None:
            continue

        # peaks are noisy — keep only the significant ones
        if kind == "peak":
            try:
                if float(str(tags.get("ele", "0")).split()[0]) < 3000:
                    continue
            except ValueError:
                continue

        names = {
            lang: tags[f"name:{lang}"]
            for lang in ("fr", "it", "de", "en")
            if f"name:{lang}" in tags
        }
        out.append(
            {
                "osm_id": f"{el['type']}/{el['id']}",
                "feature_type": kind,
                "name_default": name,
                "names": names,
                "aliases": [v for k, v in tags.items()
                            if k in ("alt_name", "old_name", "loc_name")],
                "lat": round(lat, 6),
                "lon": round(lon, 6),
                "ele": tags.get("ele"),
                "operator": tags.get("operator"),
            }
        )

    out.sort(key=lambda c: (c["feature_type"], c["name_default"]))
    print(f"{len(out)} candidates", file=sys.stderr)
    yaml.safe_dump(out, sys.stdout, allow_unicode=True, sort_keys=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
