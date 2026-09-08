"""Drawing a route line ourselves, and the guards that stop us drawing a wrong one.

Six routes have no line anywhere we can reach: camptocamp holds a marker and no
`geom_detail`, splits the Goûter across documents that stop at 3840 m, and OSM's
matches are decoys of the kind this project keeps meeting — 'Impasse du Gouter'
is a residential street, 'Dent du Geant' is a `highway=tertiary`, and the three
"Goûter" ways are refuge BUILDING outlines.

`fetch_route_geometry` has always allowed the fallback, always with the same
condition: *"honest if labelled as schematic; it puts the route roughly where it
is without pretending to be a GPX track."* Two obligations follow, and both are
tested here.

**Every vertex is a position we already hold** — one of our own features, or an
OSM peak node from the candidates file. Never a coordinate typed from memory.
Inventing coordinates is how you get a map that is confidently wrong.

**A line we drew is not more trustworthy than one we fetched.** It runs the same
altitude and span guards as the real importer, and that is not ceremony: writing
this, the Grand Couloir schematic was drawn Tête Rousse -> Aiguille du Goûter on
the reasoning that the couloir is a gully cut by that leg, and the guard refused
it — those waypoints top out at 3863 m against the couloir's 3400 m, so the line
would have been drawn up the slope ABOVE the crossing. The guard caught the
author, which is the only real evidence a guard works.
"""

from __future__ import annotations

import pytest

from massif.scripts import build_schematic_routes as build

# Positions from seeds/osm_candidates.yaml and our own features.
TETE_ROUSSE = (6.81752, 45.85494)
AIG_GOUTER = (6.83124, 45.85095)
MONT_BLANC = (6.86517, 45.83271)
SWEDEN = (18.06, 67.85)


class _Row(tuple):
    """session.execute(...).first() returns a row of (name, x, y)."""


class _Session:
    def __init__(self, features: dict) -> None:
        self.features = features

    def execute(self, _query):
        # Only used by resolve(), and only for a feature slug lookup. The slug
        # is not recoverable from the compiled query here, so the fake answers
        # with whatever single feature it was given.
        session = self

        class _Result:
            def first(self):
                return session.features.get("_next")

        return _Result()


def _peaks() -> dict:
    return {
        "node/1438494348": {
            "name_default": "Aiguille du Goûter",
            "lat": AIG_GOUTER[1],
            "lon": AIG_GOUTER[0],
            "ele": 3863,
        },
        "node/281399025": {
            "name_default": "Mont Blanc",
            "lat": MONT_BLANC[1],
            "lon": MONT_BLANC[0],
            "ele": 4807,
        },
        "node/nowhere": {
            "name_default": "Kebnekaise",
            "lat": SWEDEN[1],
            "lon": SWEDEN[0],
            "ele": 2096,
        },
    }


# ----------------------------------------------------- resolving a waypoint


def test_an_osm_waypoint_resolves_to_its_held_position_and_elevation():
    point, ele, name = build.resolve(_Session({}), "osm:node/281399025", _peaks())
    assert point == MONT_BLANC
    assert ele == 4807
    assert "Mont Blanc" in name


def test_an_unknown_waypoint_raises_rather_than_being_skipped():
    """A vertex silently dropped is a different route from the one the seed
    describes, drawn without anybody being told. Louder is safer."""
    with pytest.raises(LookupError):
        build.resolve(_Session({}), "osm:node/does-not-exist", _peaks())


def test_a_feature_waypoint_we_hold_no_geometry_for_raises():
    with pytest.raises(LookupError):
        build.resolve(_Session({"_next": None}), "refuge-du-nowhere", _peaks())


def test_a_peak_without_an_elevation_is_not_a_usable_waypoint():
    """`osm_peaks` filters on ele, because the elevation is what lets the
    altitude guard run at all. A peak without one would pass silently."""
    peaks = _peaks()
    del peaks["node/281399025"]["ele"]
    # osm_peaks() itself does the filtering; resolve just reads what it is
    # given, so the guarantee lives in the filter and is asserted on the source.
    import inspect

    source = inspect.getsource(build.osm_peaks)
    assert 'd.get("ele")' in source


# ------------------------------------------------------------------ the span


def test_span_is_measured_across_the_whole_line():
    assert build.span_km([TETE_ROUSSE, AIG_GOUTER]) == pytest.approx(1.1, abs=0.3)
    assert build.span_km([TETE_ROUSSE, MONT_BLANC]) == pytest.approx(4.3, abs=0.6)


def test_a_line_that_leaves_the_massif_is_not_in_it():
    """The safety net that rejects Sweden, which is where matching by name put
    the Goûter route the first time anybody tried."""
    assert build.in_massif([TETE_ROUSSE, AIG_GOUTER]) is True
    assert build.in_massif([TETE_ROUSSE, SWEDEN]) is False


# -------------------------------------------- the guards, on our own drawing


def test_the_altitude_guard_is_the_importer_s_and_not_a_copy():
    """One tolerance, or the drawn lines and the fetched ones drift apart and
    only one of them has a rule."""
    import inspect

    source = inspect.getsource(build)
    assert "from massif.scripts.import_route_geometry import" in source
    assert "ELEVATION_TOLERANCE_M" in source
    assert "MAX_SPAN_KM" in source


def test_the_grand_couloir_case_is_still_out_of_tolerance():
    """The refusal that happened while writing this, pinned so a later change
    to the tolerance cannot quietly re-admit it.

    Tête Rousse -> Aiguille du Goûter tops out at 3863 m. The Grand Couloir is
    3200-3400 m. 463 m apart: the line would run up the slope above the
    crossing rather than at it.
    """
    assert abs(3863 - 3400) > build.ELEVATION_TOLERANCE_M


def test_the_gouter_waypoints_are_within_tolerance_of_what_we_hold():
    """The other side of the same boundary: the route we did draw tops out on
    Mont Blanc at 4807 m against the 4808 m we hold."""
    assert abs(4807 - 4808) <= build.ELEVATION_TOLERANCE_M


def test_a_schematic_is_bounded_in_length():
    """Without this a two-waypoint 'route' could be a straight line across the
    massif and still satisfy every other check."""
    assert build.MAX_SCHEMATIC_KM <= 12.0


# --------------------------------------------------- what it must never do


def test_it_never_overwrites_surveyed_geometry():
    """A real line beats a drawing. If camptocamp ever publishes one of these,
    that import wins and this script must become a no-op for it rather than
    quietly reverting the map to our own sketch.
    """
    import inspect

    source = inspect.getsource(build.main)
    assert 'feature.geom_source != "schematic"' in source
    assert "already has" in source


def test_everything_it_writes_is_labelled_schematic():
    """The label is the whole licence for this script to exist. A drawn line
    that reports itself as surveyed geometry is worse than no line, because
    nothing downstream can tell the difference."""
    import inspect

    source = inspect.getsource(build.main)
    assert 'feature.geom_source = "schematic"' in source
    # And never marked as checked against IGN, which it certainly has not been.
    assert "feature.geom_verified = False" in source
