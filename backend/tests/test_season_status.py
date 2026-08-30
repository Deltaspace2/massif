"""Season status — "is this available THIS SEASON", ignoring the hour.

The front page colours by this, so a wrong answer here is a wrong colour on
the one screen most people will ever see.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime

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
            Fake("opening", "open", summary_en="older",
                 observed_at=datetime(2026, 7, 1, tzinfo=UTC)),
            Fake("opening", "open", summary_en="newer",
                 observed_at=datetime(2026, 8, 25, tzinfo=UTC)),
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
