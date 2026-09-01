"""French date parsing. Every fixture below is either a real Saint-Gervais
notice title or a shape municipal notices actually use."""

from datetime import UTC, date, datetime

import pytest

from massif.ingest.fr_dates import DateRange, parse_range


def d(y, m, day, end=False):
    from datetime import time as t

    return datetime.combine(
        datetime(y, m, day).date(), t(23, 59, 59) if end else t(0, 0), tzinfo=UTC
    )


def test_real_notice_same_month_range():
    """Live title: the May 2026 Mont-Blanc closure."""
    result = parse_range(
        "Fermeture temporaire de la voie normale du Mont-Blanc du 26 au 29 mai 2026"
    )
    assert result == DateRange(d(2026, 5, 26), d(2026, 5, 29, end=True), "same_month")


def test_real_notice_two_digit_numeric():
    """Live title: the refuge reopening, written 26/08/26."""
    result = parse_range("Réouverture des refuges de Tête Rousse et du Goûter le 26/08/26")
    assert result is not None
    assert result.start == d(2026, 8, 26)
    assert result.end == d(2026, 8, 26, end=True)


def test_range_crossing_months():
    result = parse_range("Fermeture du 30 mai au 2 juin 2026")
    assert result.start == d(2026, 5, 30)
    assert result.end == d(2026, 6, 2, end=True)


def test_range_crossing_new_year():
    """Both years written out, so the most specific rule must win — the
    same-month pattern would otherwise match a substring."""
    result = parse_range("Interdiction du 28 décembre 2026 au 3 janvier 2027")
    assert result.rule == "full_range"
    assert result.start == d(2026, 12, 28)
    assert result.end == d(2027, 1, 3, end=True)


def test_premier_written_as_1er():
    result = parse_range("Fermée du 1er au 5 juillet 2026")
    assert result.start == d(2026, 7, 1)
    assert result.end == d(2026, 7, 5, end=True)


def test_open_ended_until():
    result = parse_range("Voie interdite jusqu'au 30 septembre 2026")
    assert result.start is None
    assert result.end == d(2026, 9, 30, end=True)
    assert not result.bounded


def test_open_ended_from():
    result = parse_range("Accès rétabli à partir du 12 juin 2026")
    assert result.start == d(2026, 6, 12)
    assert result.end is None


def test_accents_are_optional():
    """Notices are inconsistent about accents; the parser must not care."""
    assert parse_range("du 1 au 3 fevrier 2027") == parse_range("du 1 au 3 février 2027")
    assert parse_range("du 1 au 3 aout 2026") == parse_range("du 1 au 3 août 2026")


def test_end_date_is_inclusive():
    """'du 26 au 29' includes the 29th. An exclusive end would reopen a route
    a day early — on paper, while it is still legally shut."""
    result = parse_range("du 26 au 29 mai 2026")
    assert result.end.hour == 23 and result.end.minute == 59


def test_no_dates_is_none_not_an_error():
    """Most municipal news has no dates at all. That is normal."""
    assert parse_range("L'Ambassade d'Inde en visite à Saint-Gervais") is None
    assert parse_range("") is None


def test_impossible_date_does_not_crash():
    assert parse_range("du 31 au 32 février 2026") is None


@pytest.mark.parametrize("year_text,expected", [("26", 2026), ("2026", 2026)])
def test_two_digit_years_are_this_century(year_text, expected):
    result = parse_range(f"le 26/08/{year_text}")
    assert result.start.year == expected


# ------------------------------------------------------------- describe -----


def test_describe_same_month_range():
    from massif.ingest.fr_dates import describe

    assert describe(parse_range("du 26 au 29 mai 2026")) == "26–29 May 2026"


def test_describe_single_day():
    from massif.ingest.fr_dates import describe

    assert describe(parse_range("le 26/08/26")) == "26 Aug 2026"


def test_describe_across_months_and_years():
    from massif.ingest.fr_dates import describe

    assert describe(parse_range("du 30 mai au 2 juin 2026")) == "30 May – 2 Jun 2026"
    assert (
        describe(parse_range("du 28 décembre 2026 au 3 janvier 2027")) == "28 Dec 2026 – 3 Jan 2027"
    )


def test_describe_open_ended():
    from massif.ingest.fr_dates import describe

    assert describe(parse_range("jusqu'au 30 septembre 2026")) == "until 30 Sep 2026"
    assert describe(parse_range("à partir du 12 juin 2026")) == "from 12 Jun 2026"


def test_describe_none():
    from massif.ingest.fr_dates import describe

    assert describe(None) is None


# ---------------------------------------------------- typography, and a gap


def test_a_curly_apostrophe_does_not_shorten_a_closure():
    """Found by pointing the model at a real arrêté.

    Saint-Gervais' CMS writes "jusqu’au" with U+2019. The `until` pattern
    allows a straight apostrophe only, so it missed, the search fell through to
    `single_named`, matched the "du 26 mai 2026" at the front of the phrase,
    and read a FOUR-day closure of the voie normale as a one-day one. Narrower
    than the decree, entirely plausible, and silent — accents were normalised
    from the first day here and curly quotes never were.
    """
    curly = parse_range("du 26 mai 2026 et jusqu’au 29 mai 2026")
    straight = parse_range("du 26 mai 2026 et jusqu'au 29 mai 2026")
    assert curly is not None
    assert curly.start.date() == date(2026, 5, 26)
    assert curly.end.date() == date(2026, 5, 29)
    assert (curly.start, curly.end) == (straight.start, straight.end)


def test_an_en_dash_range_reads_like_a_hyphenated_one():
    """Any CMS that prettifies text writes ranges with an en dash."""
    assert parse_range("du 26–29 mai 2026") == parse_range("du 26-29 mai 2026")


def test_a_non_breaking_space_is_still_a_space():
    assert parse_range("du 26 mai 2026 au 29 mai 2026") is not None


def test_du_x_jusqu_au_y_keeps_its_start_date():
    """The shape an arrêté actually uses. Before this rule it matched `until`
    and lost the start date, leaving a closure with no beginning."""
    found = parse_range("du 26 mai 2026 jusqu'au 29 mai 2026")
    assert found.rule == "from_until"
    assert found.start.date() == date(2026, 5, 26)
    assert found.end.date() == date(2026, 5, 29)


def test_a_bare_jusqu_au_still_has_no_start():
    """The new rule must not invent a start for a phrase that states none."""
    found = parse_range("jusqu'au 29 mai 2026")
    assert found.rule == "until"
    assert found.start is None
    assert found.end.date() == date(2026, 5, 29)


def test_a_stored_date_prints_as_the_day_the_source_wrote():
    """Dates are encoded as UTC day boundaries, and Postgres returns them in
    the server's timezone — so east of UTC an end boundary lands after midnight
    and prints one day late. "jusqu'au 26 septembre" showed as the 27th.

    Fixed once in phrase_for_now and then hit again in the review tool, which
    is why the rule lives here: this module owns what a date means, and every
    place that prints one has to agree.
    """
    from datetime import timedelta, timezone

    from massif.ingest.fr_dates import published_date

    end_of_day = datetime(2026, 9, 26, 23, 59, 59, tzinfo=UTC)
    assert published_date(end_of_day) == date(2026, 9, 26)
    # The same instant handed back by a server east of UTC.
    east = end_of_day.astimezone(timezone(timedelta(hours=8)))
    assert east.day == 27
    assert published_date(east) == date(2026, 9, 26)


def test_a_weekday_name_does_not_hide_a_date():
    """French notices write "du vendredi 12 juin", and every rule here wants a
    digit straight after "du". Refuge de Plan Glacier publishes both ends
    plainly — "Ouverture du Vendredi 12 Juin au soir, jusqu'au Mardi 8
    Septembre 2026" — and it parsed to nothing, so the hut was demoted to
    unknown under a message blaming the refuge for giving no dates."""
    found = parse_range("du Vendredi 12 Juin au soir, jusqu'au Mardi 8 Septembre 2026")
    assert found is not None
    assert found.start.date() == date(2026, 6, 12)
    assert found.end.date() == date(2026, 9, 8)


def test_only_the_end_needs_to_carry_the_year():
    """ "du 12 juin ... jusqu'au 8 septembre 2026" — the start takes the end's
    year, which is the only reading that is not a range ending before it
    starts."""
    found = parse_range("du 12 juin jusqu'au 8 septembre 2026")
    assert found.start.date() == date(2026, 6, 12)
    assert found.end.date() == date(2026, 9, 8)


def test_a_split_year_range_puts_the_start_in_the_earlier_year():
    found = parse_range("du 15 décembre jusqu'au 15 avril 2027")
    assert found.start.date() == date(2026, 12, 15)
    assert found.end.date() == date(2027, 4, 15)


def test_a_weekday_alone_is_still_not_a_date():
    assert parse_range("ouvert du vendredi au dimanche") is None


# --------------------------------------------------- the numeric shapes too


def test_jusqu_au_reads_a_numeric_date():
    """Hut websites write "gardé jusqu'au 30/08" where a mairie writes
    "jusqu'au 30 août 2026". The named-month rules could not see them at all,
    so the Refuge du Requin's own opening notice was demoted to unknown."""
    found = parse_range("jusqu'au 30/08/2026")
    assert found.start is None
    assert found.end.date() == date(2026, 8, 30)


def test_a_partir_du_reads_a_numeric_date():
    found = parse_range("à partir du 12/06/2026")
    assert found.start.date() == date(2026, 6, 12)
    assert found.end is None
