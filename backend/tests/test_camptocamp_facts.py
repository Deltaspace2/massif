"""camptocamp hut facts — matching by position, and what we refuse to publish.

This is the second facts source, and it exists for one field: custodianship,
which says whether a hut is reachable when the warden is away. It is still a
FACT — a property of the arrangement, not a dated claim about today — so it
must never reach the status pipeline.
"""


from massif.scripts.import_camptocamp_facts import (
    ALTITUDE_TOLERANCE_M,
    CUSTODIANSHIP,
    MATCH_METRES,
    lonlat,
    metres,
    read_hut,
)


def waypoint(**over):
    doc = {
        "custodianship": "always_accessible",
        "capacity": 12,
        "capacity_staffed": 74,
        "phone": "04 81 91 86 56",
        "elevation": 3165,
        "url": "https://example.org/hut",
        "locales": [
            {
                "lang": "fr",
                "title": "Refuge de Tête Rousse",
                "description": "Their community's prose, which we do not copy.",
                "access": "More prose.",
                "access_period": "Gardé de mi-juin à fin septembre.",
            }
        ],
    }
    doc.update(over)
    return doc


def test_their_prose_is_never_copied():
    """Same discipline as refuges.info. access_period is the tempting one — it
    holds the warden season — but it is free text in three languages, and
    reading it with a regex would be guessing at a public claim."""
    kept = read_hut(waypoint())
    for forbidden in ("description", "access", "access_period", "summary"):
        assert forbidden not in kept


def test_the_useful_fields_survive():
    kept = read_hut(waypoint())
    assert kept["custodianship"] == "Some shelter accessible even when unwardened"
    assert kept["capacity_staffed"] == 74
    assert kept["capacity_unstaffed"] == 12
    assert kept["phone"] == "04 81 91 86 56"


def test_a_custodianship_we_do_not_recognise_is_dropped_not_guessed():
    """This renders on a public page as though we had checked it. A value we
    have never seen is one we cannot promise to have understood."""
    kept = read_hut(waypoint(custodianship="some_new_value"))
    assert "custodianship" not in kept


def test_always_accessible_does_not_claim_the_hut_is_open():
    """The wording matters more than it looks.

    Tête Rousse and the Couvercle both carry always_accessible and both have a
    separate winter refuge that OSM maps as its own building; Tête Rousse
    reports 74 wardened places and 12 unwardened, which is that winter room.
    The enum is about access RELATIVE TO THE WARDEN. Rendering it as "open"
    would turn a fact about the arrangement into a claim about today.
    """
    assert "open" not in CUSTODIANSHIP["always_accessible"].lower()
    assert "unwardened" in CUSTODIANSHIP["always_accessible"]


def test_zero_is_missing_data_not_a_capacity_of_zero():
    """The same trap refuges.info set with `places`: 0 means nobody filled it
    in, and storing it would render as a hut that sleeps nobody."""
    kept = read_hut(waypoint(capacity=0, capacity_staffed=0))
    assert "capacity_unstaffed" not in kept
    assert "capacity_staffed" not in kept


def test_position_beats_names_across_three_languages():
    """Why this source matches on geometry and not on text.

    "Rifugio Torino" against "Refuge Torino" cost a day on refuges.info. Two
    hut records 16 m apart are one building whatever anybody called it.
    """
    ours = (45.8687, 6.8203)
    theirs = (45.86875, 6.82045)
    assert metres(ours, theirs) < MATCH_METRES
    # And a genuinely different hut an hour down the route is not swallowed.
    gouter = (45.8511, 6.8306)
    assert metres(ours, gouter) > MATCH_METRES


def test_web_mercator_is_converted_not_assumed():
    """Their API answers in EPSG:3857. Treating those numbers as degrees would
    put every hut in the Atlantic, and a silent factor error here would move
    huts by kilometres while still looking like coordinates."""
    got = lonlat({"geometry": {"geom": '{"coordinates": [764900.0, 5762000.0]}'}})
    assert got is not None
    lat, lon = got
    assert 45.5 < lat < 46.2, lat
    assert 6.5 < lon < 7.2, lon


def test_a_waypoint_with_no_geometry_is_skipped_not_defaulted():
    assert lonlat({}) is None
    assert lonlat({"geometry": {"geom": "not json"}}) is None


def test_the_altitude_tolerance_is_wider_than_the_osm_one_on_purpose():
    """Two projects surveying independently disagree by tens of metres on huts
    that are plainly the same building — refuges.info and OSM differ by 20 m on
    the Goûter. Too tight a tolerance rejects correct matches."""
    assert ALTITUDE_TOLERANCE_M >= 150
