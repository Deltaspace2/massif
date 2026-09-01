"""Swiss hut seasons from the CAS booking platform.

The whole care of this module is that `hutStatus` alone is not a season. The
real Cabane du Trient calendar in the fixture says SERVICED on all 242 days
from September to April — through the whole winter — and only 76 of them carry
a bed count. Believing the flag would publish "the Trient is wardened in
January", which is false and would look entirely reasonable on the page.
"""

import json
from datetime import UTC, date, datetime
from pathlib import Path

from massif.enums import StatementType, StatusValue
from massif.ingest.sources.hut_reservation import (
    HutReservationScraper,
    _days,
    extract,
    run_around,
)

FIXTURES = Path(__file__).parent / "fixtures"


def trient() -> str:
    return (FIXTURES / "hut_reservation_trient.json").read_text(encoding="utf-8")


def day(iso, status, beds=10):
    return {"date": f"{iso}T00:00:00Z", "hutStatus": status, "freeBeds": beds}


def envelope(*days_, slug="cabane-du-trient"):
    return json.dumps(
        {"feature_slug": slug, "hut_id": 1, "hut_name": "X", "availability": list(days_)}
    )


ON = datetime(2026, 9, 1, 12, tzinfo=UTC)


# ------------------------------------------------------- the trap in the data


def test_serviced_without_a_bed_count_is_not_a_wardened_day():
    """The Trient's winter. Every day reads SERVICED; the ones outside the
    bookable window carry no beds. Taking the flag at its word stretched the
    season from 19 September to the following September."""
    found = extract(trient(), ON)
    assert len(found) == 1
    assert found[0].valid_to.date() == date(2026, 9, 19)
    assert found[0].status == StatusValue.OPEN


def test_a_day_with_no_bed_count_breaks_a_run_rather_than_extending_it():
    """It is not a quiet "closed" either — it is no information, so a season
    can never be stretched across a gap we cannot see into."""
    found = extract(
        envelope(
            day("2026-09-01", "SERVICED", 10),
            day("2026-09-02", "SERVICED", None),
            day("2026-09-03", "SERVICED", 10),
        ),
        ON,
    )
    assert found[0].valid_to.date() == date(2026, 9, 1)


def test_closed_is_believed_without_a_bed_count():
    """There is nothing to book on a day the hut is shut, so a null there is
    the expected shape of a real claim rather than the absence of one."""
    found = extract(
        envelope(day("2026-09-01", "CLOSED", None), day("2026-09-02", "CLOSED", None)),
        ON,
    )
    assert len(found) == 1
    assert found[0].status == StatusValue.CLOSED
    assert found[0].valid_to.date() == date(2026, 9, 2)


def test_a_hut_shut_for_the_winter_is_routine_and_not_news():
    """Rule 4. A Swiss hut is closed for most of the year and that is the
    ordinary state of the world — grey, never red."""
    found = extract(envelope(day("2026-09-01", "CLOSED", None)), ON)
    assert found[0].payload["closure_kind"] == "outside_hours"
    assert found[0].severity == 0


# ------------------------------------------------------------- the mechanics


def test_the_run_is_the_stretch_containing_the_day_asked_about():
    days = [
        (date(2026, 8, 30), "CLOSED"),
        (date(2026, 8, 31), "SERVICED"),
        (date(2026, 9, 1), "SERVICED"),
        (date(2026, 9, 2), "SERVICED"),
        (date(2026, 9, 3), "CLOSED"),
    ]
    assert run_around(days, date(2026, 9, 1)) == ("SERVICED", date(2026, 8, 31), date(2026, 9, 2))
    assert run_around(days, date(2027, 1, 1)) is None


def test_a_calendar_that_does_not_cover_the_day_says_nothing():
    assert extract(envelope(day("2027-01-01", "SERVICED", 10)), ON) == []


def test_an_unrecognised_status_is_skipped_not_guessed():
    assert extract(envelope(day("2026-09-01", "RENOVATION", 10)), ON) == []


def test_unserviced_is_open_but_not_wardened():
    found = extract(envelope(day("2026-09-01", "UNSERVICED", 22)), ON)
    assert found[0].status == StatusValue.OPEN
    assert found[0].statement_type == StatementType.OPENING
    assert "unstaffed" in found[0].summary_en


def test_re_extraction_reads_the_season_current_when_we_fetched_it():
    """Not now(): re-extracting a stored calendar has to reproduce the season
    that was in force then, not whichever one today falls in."""

    class StoredDocument:
        raw_text = trient()
        raw_content = None
        published_at = None
        fetched_at = datetime(2026, 9, 15, tzinfo=UTC)

    found = HutReservationScraper().extract_stored(StoredDocument())
    assert found
    assert found[0].observed_at == StoredDocument.fetched_at
    assert found[0].valid_to.date() == date(2026, 9, 19)


def test_days_drops_what_it_cannot_read():
    assert _days([{"date": "nonsense", "hutStatus": "SERVICED", "freeBeds": 1}]) == []
    assert _days([{"hutStatus": "SERVICED", "freeBeds": 1}]) == []
