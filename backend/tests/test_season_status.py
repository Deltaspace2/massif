"""Season status — "is this available THIS SEASON", ignoring the hour.

The front page colours by this, so a wrong answer here is a wrong colour on
the one screen most people will ever see.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone

from massif.enums import StatusValue
from massif.main import _season_status


@dataclass
class Fake:
    """Only the attributes _season_status reads. A real Statement needs a
    database; this function does not, and pretending otherwise would test the
    fixture rather than the logic."""

    statement_type: str
    status: str
    severity: int = 0
    summary_en: str | None = None
    observed_at: datetime = datetime(2026, 8, 25, tzinfo=UTC)
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    payload: dict = field(default_factory=dict)


def test_a_valid_reopening_reads_as_open():
    """The bug this file was written for.

    _season_status consulted closures, restrictions and schedules, and nothing
    else. A route whose only live statement was a reopening fell through every
    branch to UNKNOWN, so the front page rendered

        "unknown — no information, not 'fine'"

    for the Goûter route on 30 Aug 2026 — while Saint-Gervais had it explicitly
    open until 25 September and the feature page said so. Claiming we have no
    information when we have some is the same species of error as a stale open.
    """
    season = _season_status(
        [Fake("opening", "open", summary_en="Reopening 26 Aug 2026")],
        has_schedule=False,
    )
    assert season["value"] is StatusValue.OPEN
    assert season["reason"] == "Reopening 26 Aug 2026"


def test_a_closure_still_outranks_a_reopening():
    """Order matters: a live decreed closure wins over an older opening."""
    season = _season_status(
        [
            Fake("opening", "open", summary_en="Reopening 26 Aug 2026"),
            Fake("closure", "closed", severity=2, summary_en="Closed 28–30 Aug"),
        ],
        has_schedule=False,
    )
    assert season["value"] is StatusValue.CLOSED
    assert season["reason"] == "Closed 28–30 Aug"


def test_the_newest_reopening_wins():
    season = _season_status(
        [
            Fake(
                "opening", "open", summary_en="older", observed_at=datetime(2026, 7, 1, tzinfo=UTC)
            ),
            Fake(
                "opening", "open", summary_en="newer", observed_at=datetime(2026, 8, 25, tzinfo=UTC)
            ),
        ],
        has_schedule=False,
    )
    assert season["reason"] == "newer"


def test_an_undated_closure_does_not_claim_the_present():
    """status=unknown is how an undated notice says "real, but not dated".

    Reading statement_type alone instead of status published the Goûter route
    as closed on the morning Saint-Gervais reopened it. Pinned here as well as
    in the extractor, because this is where that read happens.
    """
    season = _season_status(
        [Fake("closure", "unknown", summary_en="Closure notice — no dates stated")],
        has_schedule=False,
    )
    assert season["value"] is StatusValue.UNKNOWN


def test_nothing_at_all_is_unknown_not_open():
    assert _season_status([], has_schedule=False)["value"] is StatusValue.UNKNOWN


def test_a_publisher_of_seasons_with_none_covering_today_is_out_of_season():
    season = _season_status([], has_schedule=True)
    assert season["value"] is StatusValue.CLOSED
    assert season["kind"] == "out_of_season"


# --------------------------------------------------------------------------
# Re-tensing: "Reopening 26 Aug 2026" printed on 31 August, beside a green dot.

from massif.main import phrase_for_now  # noqa: E402


@dataclass
class FakeOpening:
    statement_type: str = "opening"
    summary_en: str | None = "Reopening 26 Aug 2026"
    valid_from: datetime | None = datetime(2026, 8, 26, tzinfo=UTC)
    valid_to: datetime | None = datetime(2026, 9, 25, tzinfo=UTC)


def test_a_reopening_whose_day_has_passed_reads_as_open_since():
    """summary_en is composed once at extraction and then frozen. It was true
    when the mairie published it; it does not stay true, and no stored string
    can. Re-tensed at read time instead."""
    said = phrase_for_now(FakeOpening(), datetime(2026, 8, 31, tzinfo=UTC))
    assert said == "Open since 26 Aug 2026"


def test_a_reopening_still_ahead_stays_in_the_future():
    said = phrase_for_now(FakeOpening(), datetime(2026, 8, 20, tzinfo=UTC))
    assert said == "Reopening 26 Aug 2026"


@dataclass
class FakeWardenSeason:
    """FFCAM publishes both ends of a warden season, in its own words."""

    statement_type: str = "opening"
    summary_en: str | None = "Wardened and open to the public 23 May – 13 Sep 2026"
    valid_from: datetime | None = datetime(2026, 5, 23, tzinfo=UTC)
    valid_to: datetime | None = datetime(2026, 9, 13, tzinfo=UTC)
    payload: dict | None = None

    def __post_init__(self):
        self.payload = {"wardened": True}


def test_a_warden_season_is_phrased_by_the_end_the_source_stated():
    """For a hut the end is the half that matters — the warden leaving is what
    a reader plans around, and "Open since 23 May" says nothing about it. This
    date is FFCAM's own ("Fermeture du refuge au public le 13 septembre"), not
    our staleness widening, which is what makes it printable."""
    said = phrase_for_now(FakeWardenSeason(), datetime(2026, 9, 1, tzinfo=UTC))
    assert said == "Wardened until 13 Sep 2026"


def test_the_day_printed_is_the_day_the_source_published():
    """Postgres hands timestamps back in the server's timezone. `fr_dates`
    builds "13 septembre" as 13 Sep 23:59:59 UTC, so east of UTC that end
    boundary lands after midnight and the page said "until 14 Sep" — a date
    FFCAM never printed, and a different one again depending on where the API
    happens to run."""
    east = FakeWardenSeason()
    east.valid_to = datetime(2026, 9, 13, 23, 59, 59, tzinfo=UTC).astimezone(
        timezone(timedelta(hours=8))
    )
    assert east.valid_to.day == 14  # the shape of the bug, before conversion
    said = phrase_for_now(east, datetime(2026, 9, 1, tzinfo=UTC))
    assert said == "Wardened until 13 Sep 2026"


def test_a_warden_season_never_reads_as_a_closure():
    """Most of these huts have a winter room and the operator sells "hors
    gardiennage" bookings for it. The end of the season means unstaffed, never
    shut, so this must not say "Open until" — a reader would take it as the
    building closing on the 13th, which would be us inventing a closure."""
    said = phrase_for_now(FakeWardenSeason(), datetime(2026, 9, 1, tzinfo=UTC))
    assert "until" in said
    assert "Open until" not in said
    assert "clos" not in said.lower()


def test_an_opening_with_no_warden_flag_keeps_the_start_date_wording():
    """The distinction is a property of the statement, not of the source. An
    opening that does not claim a stated end still gets "Open since"."""
    said = phrase_for_now(FakeOpening(), datetime(2026, 8, 31, tzinfo=UTC))
    assert said == "Open since 26 Aug 2026"


def test_the_widened_end_date_is_never_printed():
    """Saint-Gervais stated a reopening ON the 26th. The end of the window is
    our own staleness widening, and printing it would hand the reader a date
    the source never gave."""
    said = phrase_for_now(FakeOpening(), datetime(2026, 8, 31, tzinfo=UTC))
    assert "Sep" not in said


def test_an_undated_opening_keeps_its_stored_wording():
    opening = FakeOpening(summary_en="Reopening — no date stated", valid_from=None)
    said = phrase_for_now(opening, datetime(2026, 8, 31, tzinfo=UTC))
    assert said == "Reopening — no date stated"


def test_closures_are_never_paraphrased():
    """A closure's dates are the claim itself."""
    closure = Fake("closure", "closed", summary_en="Closed 26–29 May 2026")
    closure.valid_from = datetime(2026, 5, 26, tzinfo=UTC)
    said = phrase_for_now(closure, datetime(2026, 8, 31, tzinfo=UTC))
    assert said == "Closed 26–29 May 2026"
