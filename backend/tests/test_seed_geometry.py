"""Geometry assignment must not reuse the resolver's fuzzy key.

Live regression: the Goûter route and the Grand Couloir were both pinned on
Refuge du Goûter, and the Cosmiques arête on Refuge des Cosmiques, because
seed_features matched OSM candidates with normalise() — which strips "route",
"voie", "arête" and "refuge" so that prose mentions resolve loosely.
"""

import inspect

from massif.ingest.resolve import normalise
from massif.scripts import seed_features as mod
from massif.scripts.seed_features import POINT_LIKE, geo_key


def test_fuzzy_key_collapses_route_and_hut():
    """Demonstrates the cause: for the resolver this is a feature, not a bug."""
    assert normalise("Goûter Route") == normalise("Refuge du Goûter")


def test_strict_key_keeps_them_apart():
    assert geo_key("Goûter Route") != geo_key("Refuge du Goûter")
    assert geo_key("Arête des Cosmiques") != geo_key("Refuge des Cosmiques")
    assert geo_key("Grand Couloir du Goûter") != geo_key("Refuge du Goûter")


def test_strict_key_still_ignores_accents_and_case():
    """Strict is not literal: the same name spelled differently must match."""
    assert geo_key("Refuge du Goûter") == geo_key("REFUGE DU GOUTER")
    assert geo_key("Télésiège  des   Bossons") == geo_key("telesiege des bossons")


def test_routes_and_couloirs_are_not_point_like():
    """A route is a line. A point is the wrong shape even when the name is
    matched correctly."""
    assert "route" not in POINT_LIKE
    assert "couloir" not in POINT_LIKE
    assert "glacier" not in POINT_LIKE


def test_huts_and_lifts_are_point_like():
    assert {"hut", "lift", "lift_station", "peak"} <= POINT_LIKE


# ------------------------------------------------ a reseed must not undo work


def test_a_line_is_never_downgraded_to_a_point():
    """The loaded gun. Lifts and railways carry LineStrings imported from
    their OSM ways and relations; the seed's point assignment used to be
    unconditional, so one `seed_features` run would have silently replaced
    all twenty-nine of them with name-matched points again.

    Asserted structurally on the guard the assignment hangs off, and
    behaviourally on `_is_point`, which is what the guard asks.
    """
    from geoalchemy2 import WKBElement
    from shapely import wkb
    from shapely.geometry import LineString, Point

    # WKBElement, because that is what the session hands back for a stored
    # geometry. A bare hex string raises inside to_shape and would fall into
    # the "unreadable counts as replaceable" branch — which is exactly the
    # trap the first version of this test fell into: its LineString "passed"
    # as replaceable because the type was wrong, not because the guard was.
    assert mod._is_point(WKBElement(wkb.dumps(Point(6.95, 46.01), hex=True))) is True
    line = WKBElement(wkb.dumps(LineString([(6.95, 46.01), (6.96, 46.0)]), hex=True))
    assert mod._is_point(line) is False

    source = inspect.getsource(mod.seed_features)
    assert "replaceable = existing.geom is None or _is_point(existing.geom)" in source


def test_a_curated_pin_wins_over_the_name_lottery():
    """The Balme bug. Forms are tried in order and first hit wins, so the bare
    alias "Balme" matched a lift station called Balme fourteen kilometres from
    Le Tour. A pinned id skips the name matching entirely — and a pin that
    misses must NOT fall back to names, because the human said which object
    this is and a fallback would quietly overrule them."""
    source = inspect.getsource(mod.seed_features)
    assert 'osm_by_id.get(pinned)' in source
    assert "forms = []  # the pin answers" in source


def test_unreadable_geometry_counts_as_replaceable():
    """Refusing to touch a broken value would freeze it for ever."""
    assert mod._is_point(b"not wkb at all") is True
