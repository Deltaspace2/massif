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
    NOT_MOUNTAIN_HUTS,
    OTHER_RANGES,
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
LAC_BLANC = (45.9760, 6.8880)
DALMAZZI = (45.8930, 7.0080)


def test_the_radius_reaches_the_whole_massif():
    """The radius is the coarse filter, and it has to be generous enough.

    It was 12 km, which cut off real massif huts: Flégère at 14.2, Dalmazzi at
    15.2, Elena at 16.5, Lac Blanc at 16.7. Keeping it small to exclude the
    Beaufortain traded a wrong exclusion for a wrong inclusion, and the missing
    huts were the ones people asked about.
    """
    assert km_from_summit(*GOUTER) < RADIUS_KM
    assert km_from_summit(*TORINO) < RADIUS_KM
    assert km_from_summit(*LAC_BLANC) < RADIUS_KM, "17 km must reach the Aiguilles Rouges side"
    assert km_from_summit(*DALMAZZI) < RADIUS_KM, "17 km must reach the Italian Val Ferret"


def test_a_circle_is_not_a_massif_so_other_ranges_are_named():
    """What the radius cannot do, and why the exclusion list exists.

    Mont-Joly is 13.4 km from the summit — inside any radius wide enough to
    reach Lac Blanc — and it is in the Val Montjoie, a different range. There
    is no distance that includes one and excludes the other, so the ranges are
    named and each carries the range it actually belongs to.
    """
    assert km_from_summit(*MONT_JOLY) < RADIUS_KM, "inside the circle"
    assert "Refuge du Mont-Joly" in OTHER_RANGES, "and excluded anyway, by name"
    assert OTHER_RANGES["Refuge du Mont-Joly"], "with a reason recorded"
    # Every exclusion must say which range it belongs to, or the list becomes
    # a place to hide a hut somebody could not be bothered to classify.
    assert all(reason.strip() for reason in OTHER_RANGES.values())
    assert all(reason.strip() for reason in NOT_MOUNTAIN_HUTS.values())


def test_a_hotel_called_a_refuge_is_not_always_a_refuge():
    """The OSM query now asks for refuge-NAMED hotels, because the Refuge du
    Montenvers is tagged tourism=hotel and was invisible without it. That same
    net catches "Le Refuge des Aiglons", a hotel in Chamonix town."""
    assert "Le Refuge des Aiglons" in NOT_MOUNTAIN_HUTS


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
