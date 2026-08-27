"""Geometry assignment must not reuse the resolver's fuzzy key.

Live regression: the Goûter route and the Grand Couloir were both pinned on
Refuge du Goûter, and the Cosmiques arête on Refuge des Cosmiques, because
seed_features matched OSM candidates with normalise() — which strips "route",
"voie", "arête" and "refuge" so that prose mentions resolve loosely.
"""

from massif.ingest.resolve import normalise
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
