"""The Tour du Mont-Blanc booking portal, which is the only source in reach
that carries French, Italian and Swiss huts in one structure.

The Italian side is recorded in CLAUDE.md as blocked, because the commune of
Courmayeur does not resolve and the tourist office is the wrong kind of
publisher for a notice. This is not a notice source — it is the huts' own
booking calendar, and availability is a different claim from a decree.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from selectolax.parser import HTMLParser

from massif.enums import StatusValue
from massif.ingest.sources.tmb_refuges import (
    SEASON_GAP_DAYS,
    bookable_days,
    extract,
    hut_header,
    season_from,
)

FIXTURE = Path(__file__).parent / "fixtures" / "tmb_rifugio_bertone.html"
BERTONE = FIXTURE.read_text(encoding="utf-8")

# The observation date the fixture was captured against. Its September grid has
# beds on the 3rd and then the 11th to the 19th; everything else is --full.
CAPTURED = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)


def _page(cells: str, month: str = "Septembre2026") -> str:
    """A calendar month in the portal's own markup."""
    return (
        "<html><body><h1>Rifugio Test</h1>"
        '<div class="infos">COURMAYEUR 50pers alt. 2000m</div>'
        f'<div class="cal-month"><div class="cal-month__title">{month}</div>'
        f'<div class="cal-grid">{cells}</div></div></body></html>'
    )


def _cell(day: int | None, state: str, places: str = "–") -> str:
    num = "" if day is None else str(day)
    return (
        f'<div class="cal-cell cal-cell--{state}">'
        f'<span class="cal-cell__num">{num}</span>'
        f'<span class="cal-cell__places">{places}</span></div>'
    )


# --------------------------------------------------------------- the real page


def test_the_real_page_yields_a_name_an_altitude_and_a_capacity():
    """The altitude is half of the two screens that decide which hut this is —
    a name score alone once sent a hut season to a 4808 m route."""
    assert hut_header(HTMLParser(BERTONE)) == ("Rifugio G. Bertone", 50, 2000)


def test_only_bookable_days_are_believed():
    """--dispo and --last carry a bed count. Everything else on this page —
    641 --full days out of 731 — says nothing at all."""
    days = [day for day, _ in bookable_days(HTMLParser(BERTONE))]
    assert days == [
        date(2026, 9, 3),
        date(2026, 9, 11),
        date(2026, 9, 13),
        date(2026, 9, 14),
        date(2026, 9, 15),
        date(2026, 9, 17),
        date(2026, 9, 18),
        date(2026, 9, 19),
    ]


def test_the_statement_runs_from_today_to_the_end_of_the_selling_season():
    (statement,) = extract(BERTONE, CAPTURED)
    assert statement.status is StatusValue.OPEN
    assert statement.valid_from.date() == date(2026, 9, 2)
    assert statement.valid_to.date() == date(2026, 9, 19)
    assert statement.payload["altitude_m"] == 2000


# ------------------------------------------------- the bug the fixture caught


def test_today_being_marked_past_does_not_silence_the_source():
    """The regression that nearly shipped, and would have looked correct.

    This started out reusing `hut_reservation.run_around`, which returns the
    unbroken run containing the reference date. But this portal marks TODAY
    itself `--past` and sells from tomorrow, so that run is empty for every hut
    on every day: the source would have emitted nothing, for ever, with a green
    test suite and a dry run that printed rows.
    """
    assert date(2026, 9, 2) not in [d for d, _ in bookable_days(HTMLParser(BERTONE))]
    assert extract(BERTONE, CAPTURED), "a forward-looking calendar still speaks about now"


def test_a_scattered_calendar_is_one_season_not_a_one_day_window():
    """A busy hut is --full for weeks — Bertone on 641 of 731 days — so a
    strict contiguous run gives a window that expires the same afternoon."""
    (statement,) = extract(BERTONE, CAPTURED)
    assert (statement.valid_to - statement.valid_from).days >= 14


# ----------------------------------------------------------- what it must not say


def test_a_fully_booked_page_never_becomes_a_closure():
    """"Complet ou fermé" is the portal's own wording: full OR shut, and it
    will not say which. Reading it as closed would invent a closure out of a
    busy weekend, which is the exact shape of wrong answer this site exists to
    avoid. Silence is the honest outcome."""
    page = _page("".join(_cell(d, "full") for d in range(1, 31)))
    assert extract(page, CAPTURED) == []


def test_not_bookable_online_says_nothing_either():
    """"Non réservable en ligne (contacter le refuge)" is an absence of data,
    not a report about the building."""
    page = _page("".join(_cell(d, "unavailable") for d in range(1, 31)))
    assert extract(page, CAPTURED) == []


def test_padding_cells_carry_no_date():
    """The grid is padded to whole weeks with numberless cells. A padding cell
    that became a date would give the season days it never sold."""
    page = _page(_cell(None, "empty") + _cell(None, "empty") + _cell(4, "dispo", "12"))
    assert [d for d, _ in bookable_days(HTMLParser(page))] == [date(2026, 9, 4)]


def test_a_bookable_cell_with_no_day_number_is_skipped_not_fatal():
    """A markup change that drops the number span must cost us that day, not
    the whole run — every other hut on the portal is parsed in the same pass.

    The padding test above cannot reach this: padding is not bookable, so it is
    discarded before the number is ever read.
    """
    page = _page(
        '<div class="cal-cell cal-cell--dispo"><span class="cal-cell__places">9</span></div>'
        + _cell(4, "dispo", "12")
    )
    assert [d for d, _ in bookable_days(HTMLParser(page))] == [date(2026, 9, 4)]


# ------------------------------------------------------------ season boundaries


def test_a_gap_shorter_than_the_season_break_keeps_one_season():
    from datetime import timedelta

    days = [date(2026, 9, 4), date(2026, 9, 4) + timedelta(days=SEASON_GAP_DAYS)]
    assert season_from(days, date(2026, 9, 2)) == (date(2026, 9, 2), days[-1])


def test_a_gap_longer_than_the_season_break_ends_the_season():
    """Next summer is not this one. A hut selling beds in September and again
    in June is two seasons, and only the near one is about now."""
    from datetime import timedelta

    days = [date(2026, 9, 4), date(2026, 9, 4) + timedelta(days=SEASON_GAP_DAYS + 1)]
    assert season_from(days, date(2026, 9, 2)) == (date(2026, 9, 2), date(2026, 9, 4))


def test_a_season_that_starts_too_far_off_is_not_a_claim_about_now():
    """If the soonest bed is next June the hut is shut, and a calendar that
    exists is not a report that it is open."""
    assert season_from([date(2027, 6, 1)], date(2026, 9, 2)) is None


def test_a_season_already_over_is_skipped():
    assert season_from([date(2026, 7, 1), date(2026, 7, 4)], date(2026, 9, 2)) is None


def test_nothing_bookable_at_all_says_nothing():
    assert season_from([], date(2026, 9, 2)) is None


# ------------------------------------------------------------------- accents


def test_the_accented_months_parse():
    """The house speciality: four separate bugs have been a French literal
    compared without folding. "Décembre" and "Août" are the two that carry an
    accent, and a month that fails to parse silently drops a whole grid."""
    for month, expected in (("Décembre2026", 12), ("Août2027", 8), ("Février2027", 2)):
        page = _page(_cell(4, "dispo", "12"), month=month)
        days = [d for d, _ in bookable_days(HTMLParser(page))]
        assert days and days[0].month == expected, month
