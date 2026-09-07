"""The gate on hand-typed altitudes, and the shipped file held against it.

`features.alt_max` is what stops a name score attaching one building's facts to
another, so a wrong one here is worse than none: it does not refuse the bad
match, it blesses it. These tests are the reason the file can be trusted at
all — the figures in it were read from search results by a session that could
not open the pages.
"""

import pytest

from massif.ingest.hut_altitudes import (
    AGREEMENT_M,
    CIRCULAR_HOSTS,
    Reading,
    hold_reason,
    provenance,
    read_row,
)
from massif.ingest.hut_facts import ALTITUDE_TOLERANCE_M
from massif.scripts.import_hut_altitudes import apply_rows, load_rows

ROWS = load_rows()
BY_SLUG = {row.slug: row for row in ROWS}

# reports/2026-09-02.md, measured: no altitude in features, none in
# feature_facts, and no `ele` in OSM for any of them.
THE_NINE = {
    "auberge-de-bionnassay",
    "cabane-de-la-tour-rouge",
    "cabane-du-lac-des-vesses",
    "la-flegere",
    "refuge-de-tre-la-tete",
    "refuge-du-fioux",
    "refuge-du-montenvers",
    "refuge-le-peuty",
    "rifugio-bertone",
}


def source(url: str, value: int) -> dict:
    return {"url": url, "value": value, "retrieved": "2026-09-07"}


def row(**over) -> dict:
    raw = {
        "slug": "refuge-de-test",
        "alt_max": 2000,
        "sources": [
            source("https://www.refuges.info/point/1/", 2000),
            source("https://example.org/hut", 2000),
        ],
    }
    return {**raw, **over}


# ------------------------------------------------------------------- rules --


def test_two_agreeing_hosts_pass():
    assert hold_reason(read_row(row())) is None


def test_one_host_is_not_a_measurement():
    reason = hold_reason(read_row(row(sources=[source("https://www.refuges.info/point/1/", 2000)])))
    assert reason is not None and "one source is not a measurement" in reason


def test_two_pages_on_one_host_are_still_one_source():
    """The failure this catches is a directory quoted twice, which reads like
    corroboration and is not."""
    reason = hold_reason(
        read_row(
            row(
                sources=[
                    source("https://www.refuges.info/point/1/", 2000),
                    source("https://www.refuges.info/point/1/avis/", 2000),
                ]
            )
        )
    )
    assert reason is not None and "one source is not a measurement" in reason


def test_a_language_subdomain_is_not_a_second_source():
    reason = hold_reason(
        read_row(
            row(
                sources=[
                    source("https://en.refugedumontenvers.com/", 1913),
                    source("https://www.refugedumontenvers.com/fr/", 1913),
                ],
                alt_max=1913,
            )
        )
    )
    assert reason is not None and "one source is not a measurement" in reason


def test_a_value_nobody_published_is_refused_outright():
    """Not held — raised. Averaging two figures invents a third, and an
    altitude nobody published is one nobody can check."""
    with pytest.raises(ValueError, match="not a figure any source published"):
        hold_reason(
            read_row(
                row(
                    alt_max=2010,
                    sources=[
                        source("https://www.refuges.info/point/1/", 2000),
                        source("https://example.org/hut", 2020),
                    ],
                )
            )
        )


def test_near_agreement_still_counts():
    assert (
        hold_reason(
            read_row(
                row(
                    alt_max=1326,
                    sources=[
                        source("https://www.refuges.info/point/7103/", 1326),
                        source("https://example.org/hut", 1326 + AGREEMENT_M),
                    ],
                )
            )
        )
        is None
    )


def test_a_disagreement_wider_than_the_screen_holds_the_row():
    """Beyond the tolerance the matching screens use, two figures are not one
    hut measured twice — and picking between them is the invention this file
    exists to prevent."""
    reason = hold_reason(
        read_row(
            row(
                sources=[
                    source("https://www.refuges.info/point/1/", 2000),
                    source("https://example.org/hut", 2000),
                    source("https://example.net/hut", 2000 + ALTITUDE_TOLERANCE_M + 1),
                ]
            )
        )
    )
    assert reason is not None and "may be two buildings" in reason


def test_a_disagreement_inside_the_screen_is_recorded_not_refused():
    """La Flégère: the refuges.info figure looks like a digit swap, and it is
    kept because it is what that source will hand the matcher."""
    assert (
        hold_reason(
            read_row(
                row(
                    alt_max=1877,
                    sources=[
                        source("https://www.refuge-de-la-flegere.com/en/the-refuge/", 1877),
                        source("https://en.chamonix.com/lifts", 1877),
                        source("https://www.refuges.info/point/360/", 1807),
                    ],
                )
            )
        )
        is None
    )


def test_the_portal_we_ingest_cannot_vouch_for_itself():
    with pytest.raises(ValueError, match="cannot be what clears its own match"):
        read_row(
            row(sources=[source("https://www.montourdumontblanc.com/fr/il4-refuge.aspx", 2000)])
        )


def test_every_circular_host_carries_its_reason():
    assert all(reason for reason in CIRCULAR_HOSTS.values())


def test_an_altitude_without_provenance_is_refused():
    with pytest.raises(ValueError, match="no sources"):
        read_row({"slug": "refuge-de-test", "alt_max": 2000})


def test_a_held_row_needs_a_reason_a_person_can_read():
    reason = hold_reason(read_row(row(alt_max=None, held="OSM has no ele and nobody else says")))
    assert reason == "OSM has no ele and nobody else says"


def test_the_provenance_sentence_names_the_hosts_not_us():
    sentence = provenance(
        read_row(
            row(
                alt_max=1913,
                sources=[
                    source("https://en.refugedumontenvers.com/", 1913),
                    source("https://www.chamonix.com/x", 1913),
                ],
            )
        )
    )
    assert sentence == "Altitude 1913 m as published by chamonix.com and refugedumontenvers.com."


def test_the_provenance_sentence_credits_only_who_published_that_figure():
    """Live bug: the Flégère row records refuges.info's 1807 m so the matcher's
    disagreement is visible, and the first draft of this sentence then told the
    reader refuges.info had published 1877."""
    sentence = provenance(BY_SLUG["la-flegere"])
    assert "refuges.info" not in sentence
    assert sentence == (
        "Altitude 1877 m as published by chamonix.com and refuge-de-la-flegere.com."
    )


def test_the_host_of_a_url_ignores_www_and_language_prefixes():
    assert Reading("https://www.chamonix.com/a", 1, "2026-09-07").host == "chamonix.com"
    assert Reading("https://en.chamonix.com/a", 1, "2026-09-07").host == "chamonix.com"


# ------------------------------------------------------- the shipped file --


def test_the_file_covers_the_nine_and_nothing_else():
    """Widening this file is a decision, not a side effect: everything in it is
    a number somebody typed."""
    assert set(BY_SLUG) == THE_NINE


def test_every_shipped_row_passes_or_says_why_not():
    for row_ in ROWS:
        reason = hold_reason(row_)
        if row_.alt_max is None:
            assert reason, f"{row_.slug} is held with no reason"
        else:
            assert reason is None, f"{row_.slug}: {reason}"


def test_seven_are_ready_and_two_are_held():
    ready = {r.slug for r in ROWS if hold_reason(r) is None}
    assert ready == THE_NINE - {"cabane-du-lac-des-vesses", "cabane-de-la-tour-rouge"}


def test_every_reading_carries_a_url_and_a_date():
    for row_ in ROWS:
        for reading in row_.readings:
            assert reading.url.startswith("http"), row_.slug
            assert reading.retrieved, row_.slug


def test_the_values_are_the_ones_that_were_read():
    """Pinned so an edit to the file is deliberate. These are what unblocked
    tmb-refuges on Fioux, Le Peuty and Bertone."""
    assert BY_SLUG["refuge-du-montenvers"].alt_max == 1913
    assert BY_SLUG["la-flegere"].alt_max == 1877
    assert BY_SLUG["refuge-de-tre-la-tete"].alt_max == 1970
    assert BY_SLUG["rifugio-bertone"].alt_max == 1989
    assert BY_SLUG["refuge-du-fioux"].alt_max == 1505
    assert BY_SLUG["refuge-le-peuty"].alt_max == 1326
    assert BY_SLUG["auberge-de-bionnassay"].alt_max == 1320


# ------------------------------------------------------------- the writer --


class FakeFeature:
    def __init__(self, alt_min=None, alt_max=None, notes=None):
        self.alt_min = alt_min
        self.alt_max = alt_max
        self.notes = notes


class FakeSession:
    """Enough of a session to run the writer. The real one needs PostGIS."""

    def __init__(self, feature):
        self.feature = feature

    def scalar(self, _statement):
        return self.feature


OSM_NOTE = (
    "Position and altitude come from OpenStreetMap and have not been "
    "checked against IGN. The pin may be approximate."
)


def test_a_dry_run_writes_nothing():
    feature = FakeFeature(notes=OSM_NOTE)
    counts = apply_rows(FakeSession(feature), [BY_SLUG["refuge-du-montenvers"]], apply=False)
    assert counts["written"] == 1
    assert feature.alt_max is None
    assert feature.notes == OSM_NOTE


def test_applying_sets_the_altitude_and_says_where_it_came_from():
    """The OSM note tells the reader that the altitude comes from OSM. For
    these huts it does not, and a false sentence on a public page is the whole
    failure mode this project is built around."""
    feature = FakeFeature(notes=OSM_NOTE)
    apply_rows(FakeSession(feature), [BY_SLUG["refuge-du-montenvers"]], apply=True)
    assert feature.alt_max == 1913
    assert feature.notes.startswith(OSM_NOTE)
    assert feature.notes.endswith(
        "Altitude 1913 m as published by chamonix.com and refugedumontenvers.com."
    )


def test_a_second_run_does_not_repeat_the_sentence():
    feature = FakeFeature(notes=OSM_NOTE)
    rows = [BY_SLUG["refuge-du-montenvers"]]
    apply_rows(FakeSession(feature), rows, apply=True)
    once = feature.notes
    feature.alt_max = None  # the only way back here; the guard below is the real one
    apply_rows(FakeSession(feature), rows, apply=True)
    assert feature.notes == once


def test_an_altitude_already_held_is_never_overwritten():
    """OSM, the curated file and a person all outrank a number typed from a
    search result."""
    feature = FakeFeature(alt_max=1900, notes=OSM_NOTE)
    counts = apply_rows(FakeSession(feature), [BY_SLUG["refuge-du-montenvers"]], apply=True)
    assert counts == {"written": 0, "missing": 0, "already": 1}
    assert feature.alt_max == 1900
    assert feature.notes == OSM_NOTE


def test_a_hut_we_do_not_carry_is_counted_not_created():
    counts = apply_rows(FakeSession(None), [BY_SLUG["la-flegere"]], apply=True)
    assert counts == {"written": 0, "missing": 1, "already": 0}
