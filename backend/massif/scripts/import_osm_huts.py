"""Create hut features from the OSM candidates, for the core massif.

    python -m massif.scripts.import_osm_huts            # dry run
    python -m massif.scripts.import_osm_huts --apply

WHY THIS EXISTS. Every hut was hand-written in features_curated.yaml, which
gave us 24 while OSM knows 108 in the same bbox — and the IGN basemap draws all
of them. So the map showed green hut symbols with no marker on them, which is
the site admitting a coverage gap in the one place nobody can miss it. Steven
noticed exactly that.

WHAT IT DOES NOT DO. It does not touch a curated feature, ever: the yaml is
identity and wins. It only creates huts that are not already ours, and once
created a hut is a normal row that can be curated by hand afterwards.

THE RADIUS IS THE JUDGEMENT. Measured from the summit of Mont Blanc, because
"the massif" has no boundary in any dataset we hold. 12 km was chosen by
reading the margin rather than picking a round number:

    12 km   39 new   edge: Bivacco Mario Jachia, Refuge du Couvercle d'hiver
    14 km   47 new   edge: Refuge de Nant Borrant, Refuge du Mont-Joly
    20 km   73 new   edge: Chalet alpin du Tour, Refuge d'Anterne

At 12 km everything inside is massif. By 14 the Beaufortain and the Tour du
Mont Blanc start arriving, and those are a different mountain range. Real
massif huts DO sit outside it — Dalmazzi at 15 km, Comino at 15 — and the
answer for those is a hand-written entry, which is what the curated file is
for. A radius cannot know where a massif ends; it can only be honest about
where it stopped.
"""

from __future__ import annotations

import argparse
import math
import time

import httpx
import yaml
from sqlalchemy import select, text

from massif.db import session_scope
from massif.ingest.base import slugify
from massif.ingest.hut_facts import is_decoy
from massif.models import Feature
from massif.scripts.seed_features import SEEDS, geo_key, metres

SUMMIT = (45.8326, 6.8652)

# Fallback only. The boundary below is the real filter; this is what the script
# falls back to if seeds/massif_boundary.wkt is missing, and it is a poor
# massif — see fetch_massif_boundary.py.
RADIUS_KM = 17.0

# Two huts 120 m apart are one hut under two names. Name matching alone put
# OSM's "Rifugio Francesco Gonella" down as missing when we hold it as
# "Rifugio Gonella", and importing it would have produced a second marker on
# the same roof.
DEDUPE_METRES = 150

# Everything below is what a boundary CANNOT decide.
#
# OSM's "Massif du Mont-Blanc" ring does the coarse work now, and it does it
# far better than a circle — Mont-Joly, Moëde Anterne, Nant Borrant, the whole
# Fiz and Beaufortain fall outside it without anyone naming them. Most of this
# list is therefore no longer load-bearing; it is kept because the boundary is
# somebody else's data and could change under us, and a hut appearing in the
# Beaufortain is worth catching twice.
OTHER_RANGES = {
    "Refuge du Mont-Joly": "Mont Joly, Val Montjoie",
    "Refuge de Moëde Anterne": "Fiz",
    "Refuge d'Anterne Alfred Wills": "Fiz",
    "Abri de berger d'Alfred Wills": "Fiz",
    "Refuge de Platé": "Fiz",
    "Refuge de Varan": "Fiz",
    "Refuge de Sales": "Fiz",
    "Refuge Le Châtelet d'Ayères": "Fiz, above Passy",
    "Refuge du Col de la Croix du Bonhomme": "Beaufortain",
    "Chalet - Refuge de Nant Borrant": "Contamines, Beaufortain side",
    "Refuge de la Balme": "Contamines, Beaufortain side",
    "Refuge La Roselette": "Beaufortain",
    "Refuge de la Gittaz": "Beaufortain",
    "Auberge Refuge de la Nova": "Beaufortain",
    "Rifugio Albert Deffeyes": "Valgrisenche",
    "Abri de Villy": "Aravis side",
    "Abri de la Pierre à l'Ours": "Fiz, west of the Chamonix valley",
    "Refuge des prés": "Val Montjoie",
    # Over the Col de la Seigne in the Vallée des Glaciers, so Tarentaise side
    # rather than the massif — unlike Elena and Bonatti, which sit in the
    # Italian Val Ferret on the massif's own flank.
    "Refuge des Mottets": "Vallée des Glaciers, over the Col de la Seigne",
}

# Named "refuge" and tagged as lodging, but valley accommodation rather than a
# mountain hut. They only reach us because the OSM query now asks for
# refuge-named hotels, which is how the Refuge du Montenvers was found.
NOT_MOUNTAIN_HUTS = {
    "Le Refuge des Aiglons": "hotel in Chamonix town",
    "Refuge de Porcherey": "valley guest house",
    "rifugiolilla": "valley guest house",
    "Les Péchots": "valley shelter",
    "Le vieux Chéppy": "valley building",
}

# Huts OUTSIDE the boundary that we carry anyway. The ring is drawn tightly
# around the high massif, so the valley-floor huts on the Italian flank fall
# just outside it — and Bertone, Bonatti and Elena are huts people mean when
# they say Mont Blanc. The Aiguilles Rouges pair is Steven's call: they face
# the massif across the Chamonix valley and are what people search for.
#
# This is the honest shape of the problem. A boundary answers "is this in the
# mountain group"; it cannot answer "is this a hut people associate with the
# massif", and no dataset we have does.
KEEP_OUTSIDE = {
    "Rifugio Walter Bonatti": "Italian Val Ferret, on the massif's own flank",
    "Rifugio Elena": "head of the Italian Val Ferret, below Col Ferret",
    "Rifugio Bertone": "Italian Val Ferret, the TMB balcony above Courmayeur",
    "La Flégère": "Aiguilles Rouges, facing the massif across the valley",
    "Refuge du Lac Blanc": "Aiguilles Rouges, facing the massif",
    "Refuge de Bellachat": "Aiguilles Rouges, facing the massif",
}

OVERPASS = "https://overpass-api.de/api/interpreter"


def load_boundary():
    """The massif ring, or None if it has not been fetched.

    None means fall back to the radius rather than importing the world: a
    missing boundary file must not silently widen the net.
    """
    path = SEEDS / "massif_boundary.wkt"
    if not path.exists():
        return None
    from shapely import wkt

    return wkt.loads(path.read_text(encoding="utf-8").strip())


def km_from_summit(lat: float, lon: float) -> float:
    return math.hypot(
        (lat - SUMMIT[0]) * 111,
        (lon - SUMMIT[1]) * 111 * math.cos(math.radians(lat)),
    )


def metres_between(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(
        (a[0] - b[0]) * 111_000, (a[1] - b[1]) * 111_000 * math.cos(math.radians(a[0]))
    )


def countries(points: list[tuple[str, float, float]]) -> dict[str, str | None]:
    """Which country each point is in, from OSM admin boundaries.

    One request for all of them. Asked rather than inferred: three of the Swiss
    huts are not named "CAS", and a hut's language is not its jurisdiction.
    """
    if not points:
        return {}
    query = "[out:json][timeout:180];\n"
    for index, (_, lat, lon) in enumerate(points):
        query += f'is_in({lat},{lon})->.a{index};area.a{index}["admin_level"="2"];out tags;\n'
    for attempt in range(3):
        response = httpx.post(
            OVERPASS,
            data={"data": query},
            timeout=240,
            headers={
                "User-Agent": "massif/0.1 hut country lookup (+https://github.com/Deltaspace2/massif)"
            },
        )
        if response.status_code == 200 and response.text.lstrip().startswith("{"):
            break
        print(f"  overpass attempt {attempt + 1}: HTTP {response.status_code}")
        time.sleep(10)
    else:
        raise RuntimeError("overpass would not answer; nothing written")

    elements = response.json()["elements"]
    if len(elements) != len(points):
        # Every is_in must answer, or the answers are silently misaligned with
        # the points and every country after the gap is wrong.
        raise RuntimeError(
            f"asked about {len(points)} points, got {len(elements)} answers — "
            "refusing to guess which is which"
        )
    return {
        slug: (element.get("tags", {}).get("ISO3166-1"))
        for (slug, _, _), element in zip(points, elements, strict=True)
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write; otherwise dry run")
    parser.add_argument("--radius", type=float, default=RADIUS_KM, help="km from the summit")
    args = parser.parse_args()

    boundary = load_boundary()
    if boundary is None:
        print(f"no massif_boundary.wkt — falling back to a {args.radius:g} km radius")
    candidates = yaml.safe_load((SEEDS / "osm_candidates.yaml").read_text(encoding="utf-8")) or []
    huts = [
        c for c in candidates if c.get("feature_type") == "hut" and c.get("lat") and c.get("lon")
    ]

    with session_scope() as session:
        existing = session.scalars(select(Feature)).all()
        known_names = {
            geo_key(form) for f in existing for form in [f.name_default, *(f.aliases or [])]
        }
        # Positions come out of PostGIS rather than off the model: geom is a
        # geometry, not a pair of columns.
        known_points = [
            (slug, lat, lon)
            for slug, lat, lon in session.execute(
                # Points only. Routes are LINESTRINGs, which ST_Y refuses
                # outright — and taking their centroid instead would let a
                # route passing near a hut suppress that hut as a duplicate.
                text(
                    "SELECT slug, ST_Y(geom::geometry), ST_X(geom::geometry) "
                    "FROM features WHERE geom IS NOT NULL "
                    "AND GeometryType(geom::geometry) = 'POINT'"
                )
            ).all()
        ]

        selected = []
        skipped = {
            "far": 0,
            "decoy": 0,
            "known": 0,
            "nearby": 0,
            "range": 0,
            "lodging": 0,
        }
        for hut in huts:
            if boundary is not None:
                from shapely.geometry import Point

                in_massif = boundary.contains(Point(hut["lon"], hut["lat"]))
                if not in_massif and hut["name_default"] not in KEEP_OUTSIDE:
                    skipped["far"] += 1
                    continue
            elif km_from_summit(hut["lat"], hut["lon"]) > args.radius:
                skipped["far"] += 1
                continue
            name = hut["name_default"]
            if name in OTHER_RANGES:
                skipped["range"] += 1
                print(f"  --   {name[:38]:40} not this massif: {OTHER_RANGES[name]}")
                continue
            if name in NOT_MOUNTAIN_HUTS:
                skipped["lodging"] += 1
                print(f"  --   {name[:38]:40} {NOT_MOUNTAIN_HUTS[name]}")
                continue
            # A superseded building must not become a hut anyone can plan around.
            if is_decoy(hut["name_default"]):
                skipped["decoy"] += 1
                print(f"  --   superseded, skipped: {hut['name_default']}")
                continue
            if any(
                geo_key(f) in known_names
                for f in [hut["name_default"], *(hut.get("aliases") or [])]
            ):
                skipped["known"] += 1
                continue
            near = [
                slug
                for slug, lat, lon in known_points
                if metres_between((hut["lat"], hut["lon"]), (lat, lon)) < DEDUPE_METRES
            ]
            if near:
                skipped["nearby"] += 1
                print(f"  --   {hut['name_default'][:38]:40} is {near[0]} under another name")
                continue
            selected.append(hut)

        print(
            f"\n{len(huts)} hut candidates; inside the massif "
            f"({'boundary' if boundary is not None else f'{args.radius:g} km radius'}): "
            f"{len(huts) - skipped['far']}. Skipped {skipped['decoy']} superseded, "
            f"{skipped['known']} already ours by name, {skipped['nearby']} already "
            f"ours by position, {skipped['range']} in another range, "
            f"{skipped['lodging']} valley lodging."
            f"\n{len(selected)} to create.\n"
        )
        if not selected:
            return 0

        found = countries([(slugify(h["name_default"]), h["lat"], h["lon"]) for h in selected])

        for hut in sorted(selected, key=lambda h: -(metres(h.get("ele")) or 0)):
            slug = slugify(hut["name_default"])
            country = found.get(slug)
            altitude = metres(hut.get("ele"))
            print(f"  ok   {slug[:40]:42} {str(country):4} {str(altitude):>5} m")
            if not args.apply:
                continue
            feature = Feature(
                slug=slug,
                feature_type="hut",
                name_default=hut["name_default"],
                names=hut.get("names") or {},
                aliases=hut.get("aliases") or [],
                alt_max=altitude,
                country=country,
                geom=f"SRID=4326;POINT({hut['lon']} {hut['lat']})",
                geom_verified=False,
                external_ids={"osm": hut["osm_id"]},
                # Reader-facing: curated notes render above the directory
                # facts on the feature page. The first draft of this line was
                # written for whoever maintains the importer ("because the
                # basemap draws it and we did not") and it went straight onto
                # a public page. It also repeated what the status card already
                # says about nothing being published. This says the one thing
                # the reader cannot see: where the pin came from.
                notes=(
                    "Position and altitude come from OpenStreetMap and have not been "
                    "checked against IGN. The pin may be approximate."
                ),
            )
            session.add(feature)

        verb = "created" if args.apply else "would create"
        print(f"\n{verb} {len(selected)} huts")
        if not args.apply:
            print("dry run — nothing written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
