"""Have we re-checked a source lately — judged by ITS rhythm, not a flat number.

Separate from `stale`, which asks whether the claim has aged out. This asks
about our own diligence, and the two are independent: a decree valid until
September is not stale, but if nobody has looked in a week we must say so.
"""

from datetime import UTC, datetime, timedelta

from massif.main import UNCHECKED_INTERVALS, _unchecked

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def ago(**kwargs) -> datetime:
    return NOW - timedelta(**kwargs)


def test_never_checked_is_not_a_passing_check():
    assert _unchecked(None, 30, NOW) is True


def test_a_daily_source_is_not_flagged_the_moment_it_is_due():
    """The bug this file exists for.

    The UI asked this with a flat 24 hours. mbnr-openings' fetch interval is
    1440 minutes — exactly 24 hours — so a source running perfectly on time
    drifted into UNVERIFIED before every single run, and a badge that is on
    every day stops being read. Being due is not being missed.
    """
    daily = 1440
    assert _unchecked(ago(hours=25), daily, NOW) is False, "due, not missed"
    assert _unchecked(ago(hours=47), daily, NOW) is False
    # Two intervals: a run has actually been skipped.
    assert _unchecked(ago(hours=49), daily, NOW) is True


def test_a_thirty_minute_source_is_caught_long_before_a_day():
    """The other half of the same bug. A live lift feed that has not been read
    for six hours is badly behind, and the flat 24-hour rule called it fine."""
    live = 30
    assert _unchecked(ago(minutes=45), live, NOW) is False
    assert _unchecked(ago(hours=6), live, NOW) is True
    # The old flat threshold would have said this was fine.
    assert _unchecked(ago(hours=23), live, NOW) is True


def test_a_weekly_source_is_not_judged_by_a_daily_yardstick():
    """refuges-info runs every 10080 minutes. Three days without a check is
    normal for it and would have been badged under the flat rule."""
    weekly = 10080
    assert _unchecked(ago(days=3), weekly, NOW) is False
    assert _unchecked(ago(days=13), weekly, NOW) is False
    assert _unchecked(ago(days=15), weekly, NOW) is True


def test_a_source_with_no_cadence_still_gets_judged():
    """Judging by nothing would mean never flagging, which is the failure mode
    that matters: silence reading as health."""
    assert _unchecked(ago(days=30), None, NOW) is True
    assert _unchecked(ago(minutes=5), None, NOW) is False


def test_the_multiplier_is_what_separates_due_from_missed():
    """Pins the meaning rather than the number: at exactly one interval the
    source is due and must not be flagged; past the multiplier it has been
    missed and must be."""
    interval = 60
    assert _unchecked(ago(minutes=interval), interval, NOW) is False
    assert (
        _unchecked(ago(minutes=interval * UNCHECKED_INTERVALS + 1), interval, NOW)
        is True
    )
