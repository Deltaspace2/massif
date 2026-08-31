"""Selecting which OSM huts become features.

The hut list was 24 hand-written entries while OSM knew 108 in the same bbox,
and the IGN basemap drew all of them — so the map showed hut symbols with no
marker on them. The importer closes that, and the interesting part is what it
REFUSES: a radius that admits the Beaufortain, or a dedupe that misses, both
put a wrong hut on the map.
"""

import math

from massif.scripts.import_osm_huts import (
    DEDUPE_METRES,
    RADIUS_KM,
    km_from_summit,
    metres_between,
)

# Real coordinates, so the numbers mean something.
GOUTER = (45.8511, 6.8306)
TORINO = (45.8451, 6.9337)
MONT_JOLY = (45.8018, 6.6539)
GONELLA_OURS = (45.8193, 6.8322)
GONELLA_OSM = (45.81934, 6.83224)


def test_the_radius_keeps_the_massif_and_drops_the_beaufortain():
    """12 km was chosen by reading the margin, not by rounding.

    At 12 km everything inside is massif; by 14 the Refuge du Mont-Joly and
    Nant Borrant arrive, and those are a different range. This pins the
    decision, so raising the radius has to be a deliberate act rather than a
    quiet one.
    """
    assert km_from_summit(*GOUTER) < RADIUS_KM
    assert km_from_summit(*TORINO) < RADIUS_KM
    assert km_from_summit(*MONT_JOLY) > RADIUS_KM


def test_two_names_for_one_roof_are_one_hut():
    """The case the position check exists for.

    OSM calls it "Rifugio Francesco Gonella"; we hold "Rifugio Gonella". Name
    matching alone reported it missing, and importing it would have put a
    second marker on the same roof — the map complaint that started this,
    inverted.
    """
    assert metres_between(GONELLA_OURS, GONELLA_OSM) < DEDUPE_METRES


def test_distinct_huts_are_not_collapsed():
    """The dedupe must not be so wide it eats real neighbours. The Goûter and
    Tête Rousse are a different building an hour apart on the same route."""
    tete_rousse = (45.8687, 6.8203)
    assert metres_between(GOUTER, tete_rousse) > DEDUPE_METRES


def test_distance_helpers_agree_on_scale():
    """metres_between and km_from_summit measure the same world. A factor of
    1000 between them, wrong once, would silently make the radius 12 metres or
    the dedupe 150 km."""
    summit = (45.8326, 6.8652)
    for point in (GOUTER, TORINO, MONT_JOLY):
        km = km_from_summit(*point)
        metres = metres_between(summit, point)
        assert math.isclose(km * 1000, metres, rel_tol=0.001)
