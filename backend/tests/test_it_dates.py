"""Reading Italian dates, so the Courmayeur-side huts stop arriving undated.

`llm.py` verifies every date phrase a model returns by re-reading it here,
independently — guard 2 of the four. That check ran in French only, so an
Italian hut site saying "CHIUSURA 13 SETTEMBRE" produced a phrase this module
could not read, the statement arrived undated, and rule 3 correctly demoted it
to UNKNOWN. Reconned 9 Sep 2026: of ten Italian rifugi with no status, four
refuse in robots.txt and two are JS-rendered, so three are reachable — Torino,
Monzino and Bonatti — and all three state their season in Italian.

ONE GRAMMAR, TWO VOCABULARIES. "dal 20 giugno al 20 settembre" is "du 20 juin
au 20 septembre" with different words, so the rules are written once and
instantiated per language. What must not happen is the two bleeding into each
other: a French rule reading Italian prose with grammar it does not have, or
the Italian bare-date rule firing inside French text. Most of this file is
about that.
"""

from __future__ import annotations

from massif.ingest.fr_dates import MONTHS, MONTHS_IT, parse_range


def r(text: str):
    return parse_range(text)


# --------------------------------------------------------------- it reads


def test_a_two_month_italian_season():
    got = r("Il rifugio è aperto dal 20 giugno al 20 settembre 2026")
    assert got is not None
    assert (got.start.month, got.start.day) == (6, 20)
    assert (got.end.month, got.end.day) == (9, 20)


def test_an_italian_closing_date_with_no_connective_at_all():
    """The Monzino case, verbatim from the site: "!! CHIUSURA 13 SETTEMBRE".
    No "il", no "dal" — nothing in front of the day. French notices always
    carry a connective, which is why this shape is Italian-only."""
    got = r("!! CHIUSURA 13 SETTEMBRE 2026")
    assert got is not None
    assert (got.start.month, got.start.day) == (9, 13)


def test_fino_al_is_an_end_with_no_start():
    got = r("aperto fino al 15 settembre 2026")
    assert got is not None
    assert got.start is None
    assert (got.end.month, got.end.day) == (9, 15)


def test_entro_il_also_reads_as_an_end():
    got = r("prenotazione entro il 30 agosto 2026")
    assert got is not None and got.start is None
    assert (got.end.month, got.end.day) == (8, 30)


def test_a_partire_dal_is_a_start_with_no_end():
    got = r("aperto a partire dal 1 luglio 2026")
    assert got is not None
    assert (got.start.month, got.start.day) == (7, 1)
    assert got.end is None


def test_a_range_inside_one_month():
    got = r("chiuso dal 3 al 9 agosto 2026")
    assert got is not None
    assert (got.start.day, got.end.day) == (3, 9)
    assert got.start.month == got.end.month == 8


def test_the_end_is_inclusive_to_the_last_second_like_the_french_side():
    got = r("dal 3 al 9 agosto 2026")
    assert (got.end.hour, got.end.minute, got.end.second) == (23, 59, 59)


def test_italian_weekdays_are_stripped_rather_than_confusing_the_match():
    """The weekday sits between the connective and the day, so leaving it in
    breaks adjacency and the range rule cannot match at all.

    Asserting the RULE, not just that something parsed: the first version of
    this test used "da lunedì 3 a domenica 9 agosto 2026", which still parsed
    with the weekdays left in — via the bare single-date rule on "9 agosto
    2026" — and so passed with the stripping deleted.
    """
    got = r("chiuso dal lunedì 3 al giovedì 9 agosto 2026")
    assert got is not None
    assert got.rule == "same_month:it", "the weekdays broke the range match"
    assert (got.start.day, got.end.day) == (3, 9)


def test_every_italian_month_is_known():
    for name, number in MONTHS_IT.items():
        got = r(f"dal 1 {name} al 2 {name} 2026")
        assert got is not None, name
        assert got.start.month == number, name


def test_an_impossible_italian_date_is_not_a_crash():
    """31 febbraio is a parse failure, and the loop moves on rather than
    raising — same contract as the French side."""
    assert r("dal 31 febbraio al 1 marzo 2026") is not None or True
    assert r("il 31 febbraio 2026") is None


# ------------------------------------------------- and it is traceable as Italian


def test_an_italian_parse_is_labelled_as_one():
    """`DateRange.rule` exists so a surprising parse can be traced to its rule.
    With two languages sharing the rule names, the language is half of that."""
    assert r("dal 20 giugno al 20 settembre 2026").rule.endswith(":it")


def test_french_labels_are_untouched():
    """`llm.py` appends ASSUMED to this string and tests assert the bare names.
    French must keep its exact labels or both break."""
    assert r("du 26 mai 2026 au 29 mai 2026").rule == "full_range"
    assert r("jusqu'au 30 août 2026").rule == "until"
    assert r("du 26 au 29 mai 2026").rule == "same_month"


# ------------------------------------------- the two languages stay apart


def test_a_french_notice_never_matches_an_italian_rule():
    for text in (
        "Fermeture temporaire de la voie normale du 26 au 29 mai 2026",
        "Réouverture des refuges le 26/08/26",
        "gardé jusqu'au 30/08/2026",
    ):
        got = r(text)
        assert got is not None
        assert not got.rule.endswith(":it"), text


def test_the_bare_date_rule_is_offered_to_italian_only():
    """Asserted structurally, because behaviourally it is nearly invisible.

    The first version of this test used "3 personnes en juin 2026" and claimed
    to prove the point — but the day and the month are not adjacent there, so
    it passes with the rule offered to French as well. The vocabulary flag is
    the actual guarantee, so that is what is checked.

    French notices always put a connective in front of a date; Italian hut
    sites write "CHIUSURA 13 SETTEMBRE" with nothing at all. Widening the
    French surface buys nothing and can only cost.
    """
    from massif.ingest.fr_dates import _FR, _IT

    assert _IT.bare_single is True
    assert _FR.bare_single is False


def test_an_italian_month_alone_is_not_read_by_a_french_rule():
    """`novembre` is spelled the same in both. It is 11 either way, so the
    merged lookup is safe — but the French pattern must still not claim it out
    of Italian grammar."""
    got = r("dal 1 novembre al 30 novembre 2026")
    assert got is not None
    assert got.rule.endswith(":it")
    assert got.start.month == 11


def test_the_month_tables_disagree_nowhere_they_overlap():
    """The whole justification for one merged lookup in the dispatch."""
    shared = set(MONTHS) & set(MONTHS_IT)
    assert shared == {"novembre"}
    for name in shared:
        assert MONTHS[name] == MONTHS_IT[name]


def test_no_date_at_all_is_still_none_and_not_an_error():
    assert r("Il rifugio è raggiungibile in tre ore") is None
