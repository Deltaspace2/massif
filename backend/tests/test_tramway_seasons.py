"""Tramway du Mont-Blanc running periods.

This railway is the access for the Goûter route — "its closure closes the
normal approach" — and until this source it was a feature we carried with
nothing watching it. The care here is about not overstating what a timetable
is: it says when trains are scheduled, never that one is running today.
"""

from datetime import UTC, datetime
from pathlib import Path

from massif.enums import StatementType, StatusValue
from massif.ingest.sources.tramway_mont_blanc import (
    TARGET_SLUG,
    TramwayMontBlancScraper,
    extract,
    periods,
)

FIXTURES = Path(__file__).parent / "fixtures"
FETCHED = datetime(2026, 9, 1, 12, tzinfo=UTC)


def page() -> str:
    return (FIXTURES / "tmb_home.html").read_text(encoding="utf-8")


def test_the_published_running_periods_are_read():
    found = extract(page(), FETCHED)
    assert [s.original_text for s in found] == [
        "Du 13/06/2026 au 03/07/2026",
        "Du 04/07/2026 au 30/08/2026",
        "Du 31/08/2026 au 27/09/2026",
    ]
    last = found[-1]
    assert last.valid_from.date() == datetime(2026, 8, 31).date()
    assert last.valid_to.date() == datetime(2026, 9, 27).date()


def test_a_timetable_never_claims_the_train_is_running():
    """mbnr-openings' rule, and for the same reason: a schedule says what is
    planned. This railway stops for weather, and a green dot on a day it is
    held would be exactly the confident wrong answer this site exists to
    avoid. The statement still carries its dates, which is what feeds
    `season` — the question a trip planner actually asks."""
    for statement in extract(page(), FETCHED):
        assert statement.status == StatusValue.UNKNOWN
        assert statement.statement_type == StatementType.OPENING
        assert statement.payload["schedule"] is True
        assert statement.valid_from is not None and statement.valid_to is not None


def test_the_feature_is_named_outright_never_fuzzy_matched():
    """The operator's own single-feature site. There is nothing to guess at,
    and guessing is how a hut season once reached a 4808 m route."""
    for statement in extract(page(), FETCHED):
        assert statement.feature_slug == TARGET_SLUG


def test_each_period_is_counted_once():
    """A period counted twice writes two statements that supersede each other
    on every run — churn that reads as the operator changing their mind.

    Tested against a select that actually repeats an option. The live page does
    not (the repeats are in the tab markup, which this does not read), so
    asserting against the fixture alone would pass with the dedupe deleted.
    """
    assert len(periods(page())) == 3
    repeated = (
        '<select class="tmb-periode-select">'
        "<option>Du 31/08/2026 au 27/09/2026</option>"
        "<option>Du 31/08/2026 au 27/09/2026</option>"
        "</select>"
    )
    assert periods(repeated) == ["Du 31/08/2026 au 27/09/2026"]


def test_the_operators_own_element_wins_over_the_page_builders():
    """`select.tmb-periode-select` is purpose-built for this railway; the
    Elementor tab spans are whatever laid the page out, and there are ten of
    them against the select's three. Today both happen to yield the same three
    periods once the date pattern has filtered them, so only a page where they
    DISAGREE can show which one is being read."""
    conflicting = (
        '<span class="e-n-tab-title-text">Du 01/01/2026 au 02/01/2026</span>'
        '<select class="tmb-periode-select">'
        "<option>Du 31/08/2026 au 27/09/2026</option>"
        "</select>"
    )
    assert periods(conflicting) == ["Du 31/08/2026 au 27/09/2026"]


def test_a_period_shaped_like_a_date_but_impossible_is_skipped_not_guessed():
    """31 February matches the date PATTERN and fails to be a date.

    The earlier version of this test used "Du 31/08 au 27/09", which never
    reaches the parser at all — the pattern requires a four-digit year, so the
    regex rejected it and the check being tested here was never run. An
    impossible day is what separates the two.
    """
    impossible = (
        '<select class="tmb-periode-select"><option>Du 31/02/2026 au 27/09/2026</option></select>'
    )
    assert periods(impossible) == ["Du 31/02/2026 au 27/09/2026"]
    assert extract(impossible, FETCHED) == []


def test_a_period_with_no_year_is_not_even_offered_to_the_parser():
    html = '<select class="tmb-periode-select"><option>Du 31/08 au 27/09</option></select>'
    assert periods(html) == []
    assert extract(html, FETCHED) == []


def test_a_page_that_stopped_publishing_periods_yields_nothing():
    """Not an error, but it must not look like a railway that publishes
    nothing — collect() says so out loud."""
    assert extract("<html><body><p>Horaires</p></body></html>", FETCHED) == []


def test_re_extraction_dates_from_the_document_not_from_now():
    class StoredDocument:
        raw_text = None
        raw_content = None
        published_at = None
        fetched_at = datetime(2026, 6, 20, 8, tzinfo=UTC)

    StoredDocument.raw_content = page().encode("utf-8")
    found = TramwayMontBlancScraper().extract_stored(StoredDocument())
    assert found
    assert all(s.observed_at == StoredDocument.fetched_at for s in found)
