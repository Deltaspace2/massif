"""French date parsing. Every fixture below is either a real Saint-Gervais
notice title or a shape municipal notices actually use."""

from datetime import UTC, datetime

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
    result = parse_range(
        "Réouverture des refuges de Tête Rousse et du Goûter le 26/08/26"
    )
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
        describe(parse_range("du 28 décembre 2026 au 3 janvier 2027"))
        == "28 Dec 2026 – 3 Jan 2027"
    )


def test_describe_open_ended():
    from massif.ingest.fr_dates import describe

    assert describe(parse_range("jusqu'au 30 septembre 2026")) == "until 30 Sep 2026"
    assert describe(parse_range("à partir du 12 juin 2026")) == "from 12 Jun 2026"


def test_describe_none():
    from massif.ingest.fr_dates import describe

    assert describe(None) is None
