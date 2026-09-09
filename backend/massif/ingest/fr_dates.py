"""French date-range parsing for municipal notices.

Shared by every French official source, so it lives here rather than in one
scraper. Saint-Gervais puts its dates in the notice title:

    "Fermeture temporaire de la voie normale du Mont-Blanc du 26 au 29 mai 2026"
    "Réouverture des refuges de Tête Rousse et du Goûter le 26/08/26"

Both readable by rule, which is why this exists instead of an LLM call. The
model earns its place on body prose later; it is not needed to read a date.

Everything returns timezone-aware UTC datetimes with the end date inclusive to
23:59:59, because a closure "du 26 au 29" includes the 29th.
"""

from __future__ import annotations

import calendar
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, date, datetime
from datetime import time as dtime

MONTHS: dict[str, int] = {
    "janvier": 1,
    "fevrier": 2,
    "mars": 3,
    "avril": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7,
    "aout": 8,
    "septembre": 9,
    "octobre": 10,
    "novembre": 11,
    "decembre": 12,
}

# Italian, for the Courmayeur-side hut websites. Kept as its own table rather
# than merged into MONTHS, because the month name is what tells the two
# languages apart in a pattern: a French rule must not match Italian prose and
# read "dal 20 al 30" with French grammar it does not have.
#
# Only `novembre` is spelled identically in both, and it is 11 in both, so the
# merged lookup below is unambiguous.
MONTHS_IT: dict[str, int] = {
    "gennaio": 1,
    "febbraio": 2,
    "marzo": 3,
    "aprile": 4,
    "maggio": 5,
    "giugno": 6,
    "luglio": 7,
    "agosto": 8,
    "settembre": 9,
    "ottobre": 10,
    "novembre": 11,
    "dicembre": 12,
}

# What the dispatch looks a matched month name up in. Safe to merge: each
# language's patterns only ever offer their own month names.
_MONTHS_ANY: dict[str, int] = {**MONTHS, **MONTHS_IT}

_MONTH_ALT = "|".join(MONTHS)
_MONTH_ALT_IT = "|".join(MONTHS_IT)
_DAY = r"(\d{1,2})(?:\s*er)?"
_NUM = r"(\d{1,2})/(\d{1,2})/(\d{2,4})"


def published_date(moment: datetime) -> date:
    """The calendar day an instant stands for, as the source wrote it.

    Dates here are encoded as UTC day boundaries: "13 septembre" becomes 13 Sep
    00:00–23:59:59 UTC. Postgres hands the value back in the server's own
    timezone, so east of UTC that end boundary lands after midnight and the day
    reads one later — "wardened until 14 Sep" for a season published as ending
    on the 13th, and "until 27 septembre" for a hut that said the 26th.

    Fixed once in phrase_for_now and then hit again in the review tool, which
    is why it lives here now: this module owns what a date MEANS, and every
    place that prints one has to agree.
    """
    return moment.astimezone(UTC).date()


def strip_accents(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c))


# Typographic punctuation, folded to the ASCII the patterns are written in.
#
# Accents were normalised from the first day here — rule 1 — and curly quotes
# never were. Saint-Gervais' CMS writes "jusqu’au" with U+2019, so the `until`
# pattern (which allows a straight apostrophe) missed, the search fell through
# to `single_named`, matched the "du 26 mai 2026" at the front of the phrase,
# and read a four-day closure of the voie normale as a ONE-day one. Silent,
# plausible, and narrower than the decree.
#
# Dashes for the same reason: "du 26–29 mai" is a range written with an en
# dash on any CMS that prettifies text.
_TYPOGRAPHIC = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u02bc": "'",
        "\u201b": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
        "\u00a0": " ",
        "\u202f": " ",
        "\u2009": " ",
    }
)


# Weekday names carry no date information and sit exactly where the patterns
# expect a number: French notices write "du vendredi 12 juin", and every rule
# here wants a digit straight after "du". Refuge de Plan Glacier publishes
# "Ouverture du Vendredi 12 Juin au soir, jusqu'au Mardi 8 Septembre 2026" —
# both ends stated plainly — and it parsed to nothing, so the hut was demoted
# to unknown under a message blaming the source for giving no dates.
_WEEKDAYS = re.compile(
    r"\b(lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche"
    # Italian, accents already stripped by the time this runs:
    # "mercoledì" arrives as "mercoledi".
    r"|lunedi|martedi|mercoledi|giovedi|venerdi|sabato|domenica)\b"
)


def _norm(text: str) -> str:
    folded = strip_accents(text).translate(_TYPOGRAPHIC).lower()
    folded = _WEEKDAYS.sub(" ", folded)
    return re.sub(r"\s+", " ", folded).strip()


def _year(value: str) -> int:
    """Two-digit years are this century. '26' means 2026, not 1926 — these are
    forward-looking municipal notices, never historical."""
    number = int(value)
    return number if number > 99 else 2000 + number


def _at(year: int, month: int, day: int, end: bool = False) -> datetime:
    moment = dtime(23, 59, 59) if end else dtime(0, 0)
    return datetime.combine(datetime(year, month, day).date(), moment, tzinfo=UTC)


@dataclass(frozen=True)
class DateRange:
    start: datetime | None
    end: datetime | None
    # Which pattern matched — recorded so a surprising parse can be traced
    # back to its rule rather than guessed at.
    rule: str

    @property
    def bounded(self) -> bool:
        return self.start is not None and self.end is not None


# ONE GRAMMAR, TWO VOCABULARIES.
#
# The shapes below are the same in both languages — "dal 20 giugno al 20
# settembre" is "du 20 juin au 20 septembre" with different words — so the
# rules are written once and instantiated per language. Duplicating them would
# mean duplicating the parts that are actually subtle: the year-crossing in
# from_until_split, and the ordering.
#
# ORDERING WITHIN A LANGUAGE IS LOAD-BEARING: most specific first, because
# "du 28 décembre 2026 au 3 janvier 2027" also contains a substring matching
# the same-month pattern.
#
# ORDERING BETWEEN THE LANGUAGES IS NOT, and the comment here used to claim it
# was. The two vocabularies share no connective and only one month name
# (`novembre`, 11 in both), so no Italian pattern can match French prose or the
# reverse — swapping the order changes nothing, which a mutation confirmed.
# French stays first as a statement of precedence, not as a guard.
@dataclass(frozen=True)
class _Vocab:
    lang: str
    months: str
    frm: str
    to: str
    until: str
    since: str
    on: str
    # Italian hut sites write "CHIUSURA 13 SETTEMBRE 2026" — a date with no
    # connective in front of it at all. French notices always carry one, and
    # allowing a bare day-month there would make `parse_range` fire on any
    # number that happens to precede a month name.
    bare_single: bool


_FR = _Vocab(
    lang="fr",
    months=_MONTH_ALT,
    frm=r"du",
    to=r"au",
    until=r"jusqu\'?\s*au",
    since=r"a\s+partir\s+du",
    on=r"le",
    bare_single=False,
)

_IT = _Vocab(
    lang="it",
    months=_MONTH_ALT_IT,
    frm=r"dal",
    to=r"al",
    until=r"(?:fino\s+al|entro\s+il)",
    since=r"(?:a\s+partire\s+dal|dal)",
    on=r"il",
    bare_single=True,
)


def _patterns_for(v: _Vocab) -> list[tuple[str, str, re.Pattern]]:
    """(kind, lang, pattern) for one language, most specific first."""
    m, d, y = v.months, _DAY, r"(\d{4})"
    out = [
        ("full_range", re.compile(rf"{v.frm}\s+{d}\s+({m})\s+{y}\s+{v.to}\s+{d}\s+({m})\s+{y}")),
        ("split_month", re.compile(rf"{v.frm}\s+{d}\s+({m})\s+{v.to}\s+{d}\s+({m})\s+{y}")),
        ("same_month", re.compile(rf"{v.frm}\s+{d}\s+{v.to}\s+{d}\s+({m})\s+{y}")),
        (
            "numeric_range",
            re.compile(rf"{v.frm}\s+(\d{{1,2}})/(\d{{1,2}})/(\d{{2,4}})\s+{v.to}\s+(\d{{1,2}})/(\d{{1,2}})/(\d{{2,4}})"),
        ),
        # Both ends stated, but not in the "from X to Y" shape full_range
        # wants: "du 26 mai 2026 et jusqu'au 29 mai 2026". Real, from an
        # arrêté — before this it fell through to `until` and lost its start.
        (
            "from_until",
            re.compile(rf"{v.frm}\s+{d}\s+({m})\s+{y}[^0-9]{{0,24}}?{v.until}\s+{d}\s+({m})\s+{y}"),
        ),
        # Both ends stated, only the second carrying a year. The first takes
        # the second's year, the only reading that is not a range ending
        # before it starts.
        (
            "from_until_split",
            re.compile(rf"{v.frm}\s+{d}\s+({m})\b[^0-9]{{0,24}}?{v.until}\s+{d}\s+({m})\s+{y}"),
        ),
        ("until", re.compile(rf"{v.until}\s+{d}\s+({m})\s+{y}")),
        # The numeric forms of the same two shapes. Hut websites write "gardé
        # jusqu'au 30/08" where a mairie writes "jusqu'au 30 août 2026".
        ("until_numeric", re.compile(rf"{v.until}\s+(\d{{1,2}})/(\d{{1,2}})/(\d{{2,4}})")),
        (
            "from_numeric",
            re.compile(rf"(?:{v.since}|{v.frm})\s+{_NUM}"),
        ),
        ("from", re.compile(rf"{v.since}\s+{d}\s+({m})\s+{y}")),
        ("single_named", re.compile(rf"(?:{v.on}|{v.frm})\s+{d}\s+({m})\s+{y}")),
        ("single_numeric", re.compile(rf"{v.on}\s+(\d{{1,2}})/(\d{{1,2}})/(\d{{2,4}})")),
    ]
    if v.bare_single:
        # Last, so every connective form is tried first.
        out.append(("single_named", re.compile(rf"\b{d}\s+({m})\s+{y}")))
    return [(kind, v.lang, pattern) for kind, pattern in out]


_PATTERNS: list[tuple[str, str, re.Pattern]] = _patterns_for(_FR) + _patterns_for(_IT)


def parse_range(text: str) -> DateRange | None:
    """First matching rule wins. Returns None when no date is present at all —
    which is a normal outcome, not a failure: most municipal news has no dates."""
    flat = _norm(text)

    for kind, lang, pattern in _PATTERNS:
        match = pattern.search(flat)
        if not match:
            continue
        groups = match.groups()
        # French keeps its bare label: tests and llm.py's ASSUMED suffix
        # both key off the exact strings, and an Italian parse should be
        # traceable as one.
        rule = kind if lang == "fr" else f"{kind}:{lang}"

        try:
            if kind == "full_range":
                d1, m1, y1, d2, m2, y2 = groups
                return DateRange(
                    _at(_year(y1), _MONTHS_ANY[m1], int(d1)),
                    _at(_year(y2), _MONTHS_ANY[m2], int(d2), end=True),
                    rule,
                )
            if kind == "split_month":
                d1, m1, d2, m2, year = groups
                # A range crossing New Year is written with both years, so it
                # matches full_range above; here both months share one year.
                return DateRange(
                    _at(_year(year), _MONTHS_ANY[m1], int(d1)),
                    _at(_year(year), _MONTHS_ANY[m2], int(d2), end=True),
                    rule,
                )
            if kind == "same_month":
                d1, d2, month, year = groups
                return DateRange(
                    _at(_year(year), _MONTHS_ANY[month], int(d1)),
                    _at(_year(year), _MONTHS_ANY[month], int(d2), end=True),
                    rule,
                )
            if kind == "numeric_range":
                d1, m1, y1, d2, m2, y2 = groups
                return DateRange(
                    _at(_year(y1), int(m1), int(d1)),
                    _at(_year(y2), int(m2), int(d2), end=True),
                    rule,
                )
            if kind == "from_until":
                d1, m1, y1, d2, m2, y2 = groups
                return DateRange(
                    _at(_year(y1), _MONTHS_ANY[m1], int(d1)),
                    _at(_year(y2), _MONTHS_ANY[m2], int(d2), end=True),
                    rule,
                )
            if kind == "from_until_split":
                d1, m1, d2, m2, year = groups
                start = _at(_year(year), _MONTHS_ANY[m1], int(d1))
                end = _at(_year(year), _MONTHS_ANY[m2], int(d2), end=True)
                if start > end:
                    # A season stated across new year: the start belongs to the
                    # year before the one the end names.
                    start = _at(_year(year) - 1, _MONTHS_ANY[m1], int(d1))
                return DateRange(start, end, rule)
            if kind == "until":
                day, month, year = groups
                end = _at(_year(year), _MONTHS_ANY[month], int(day), end=True)
                return DateRange(None, end, rule)
            if kind == "until_numeric":
                day, month, year = groups
                return DateRange(None, _at(_year(year), int(month), int(day), end=True), rule)
            if kind == "from_numeric":
                day, month, year = groups
                return DateRange(_at(_year(year), int(month), int(day)), None, rule)
            if kind == "from":
                day, month, year = groups
                return DateRange(_at(_year(year), _MONTHS_ANY[month], int(day)), None, rule)
            if kind == "single_named":
                day, month, year = groups
                start = _at(_year(year), _MONTHS_ANY[month], int(day))
                last = _at(_year(year), _MONTHS_ANY[month], int(day), end=True)
                return DateRange(start, last, rule)
            if kind == "single_numeric":
                day, month, year = groups
                start = _at(_year(year), int(month), int(day))
                return DateRange(start, _at(_year(year), int(month), int(day), end=True), rule)
        except (ValueError, KeyError):
            # An impossible date (31 février) is a parse failure, not a crash.
            # Keep trying less specific rules.
            continue

    return None


MONTH_EN = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
]


# How far into a month each word reaches. Two bounds, because a worded end is
# read as the days it CERTAINLY covers: a start takes the latest day the word
# allows, an end the earliest, and the window is always a subset of what the
# words permit rather than a superset.
QUALIFIERS = {"debut": (1, 10), "mi": (11, 20), "fin": (21, 31)}

_COARSE_END = re.compile(
    r"(?:(\d{1,2})\s+)?(?:(debut|mi|fin)\s*-?\s*)?(" + "|".join(MONTHS) + r")\b(?:\s+(\d{4}))?"
)


def _last_day(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


# What must sit IMMEDIATELY before a lone worded end for it to mean anything.
# Adjacency is the whole guard, and the reason is in the data: the Refuge du
# Requin publishes "jusqu'au 30/08 puis les WE début septembre". Looking
# anywhere earlier in the phrase finds "jusqu'au", pairs it with "début
# septembre" and moves the end of the season eight days later than the refuge
# said. The weekends after are not the season.
_ENDS_AT = re.compile(r"jusqu'?\s*(?:au?|en)\s+(?:l[ae]\s+|l'\s*)?$")
_STARTS_AT = re.compile(r"(?:a\s+partir\s+d[eu]|des|depuis)\s+(?:l[ae]\s+|l'\s*)?$")


def _one_ended(flat: str, match: re.Match, year: int) -> DateRange | None:
    """One worded end, and the preposition in front of it says which end.

    "La cabane est ouverte et gardiennée jusqu'à la fin septembre 2026" states
    an end and no start, and that is the commonest shape on a hut's own page.
    Requiring two ends threw it away, and the review card blamed the refuge for
    a silence that was our parser's.

    An end takes the EARLIEST day its word allows and a start the latest, the
    same direction as a two-ended phrase: what we publish is always a subset of
    what the words permit. So "jusqu'à la fin septembre" ends on the 21st. The
    hut may well be staffed to the 30th; it certainly is to the 21st, and
    claiming the days in between would be us saying something nobody published.

    A worded end with no preposition governing it is not a claim about a
    window — "puis les WE début septembre" — and gets the same silence as no
    phrase at all.
    """
    day, word, month, explicit_year = match.groups()
    if not day and not word:
        return None  # a bare month name is not a date
    before = flat[: match.start()]
    ends_at = bool(_ENDS_AT.search(before))
    starts_at = bool(_STARTS_AT.search(before))
    if ends_at == starts_at:  # neither, or a phrase that says both at once
        return None

    on = int(explicit_year) if explicit_year else year
    month_number = _MONTHS_ANY[month]
    number = int(day) if day else QUALIFIERS[word][0 if ends_at else 1]
    number = min(number, _last_day(on, month_number))
    if ends_at:
        return DateRange(None, _at(on, month_number, number, end=True), "coarse")
    return DateRange(_at(on, month_number, number), None, "coarse")


def parse_coarse_range(text: str, year: int, *, may_cross_year: bool = False) -> DateRange | None:
    """A season written in WORDS, narrowed to the days it certainly covers.

    `parse_range` reads dates. This reads the other thing these pages publish:
    "De début juin au 24 août 2026" — one worded end and one exact — or the
    Abri Simond's "à partir de fin septembre jusqu'à mi février". Each end may
    be worded or exact in any mix; an end that is neither is not an end, and a
    phrase without two of them gets the same silence as no phrase at all.

    This is not a loosening of rule 3. An undated notice still says nothing;
    a season bounded in words IS bounded, and every caller marks the result
    approximate because the narrowing is ours and not the source's.

    `may_cross_year` is off by default and every caller has to mean it.
    FFCAM's seasons never cross — "Printemps : 14 mars au 3 mai" — so reading
    a backwards span there as a fourteen-month one would be the plausible,
    silent, wrong answer this codebase keeps writing rules about. A hut's own
    winter opening does cross, and for that caller it is the only reading.
    """
    flat = _norm(text)
    matches = list(_COARSE_END.finditer(flat))
    if len(matches) == 1:
        return _one_ended(flat, matches[0], year)
    if len(matches) != 2:
        return None

    ends = []
    for index, match in enumerate(matches):
        day, word, month, explicit_year = match.groups()
        if not day and not word:
            return None  # a bare month name is not a date
        month_number = _MONTHS_ANY[month]
        on = int(explicit_year) if explicit_year else year
        number = int(day) if day else QUALIFIERS[word][1 if index == 0 else 0]
        number = min(number, _last_day(on, month_number))
        ends.append((on, month_number, number))

    (y1, m1, d1), (y2, m2, d2) = ends
    start = _at(y1, m1, d1)
    end = _at(y2, m2, d2, end=True)
    if start >= end:
        if not may_cross_year or explicit_year:
            return None
        # September to February is next February. Only when the phrase did not
        # state its own year: a source that wrote both years and still ran
        # backwards has said something we do not understand, and guessing at
        # it is worse than queueing it.
        end = _at(y2 + 1, m2, d2, end=True)
    return DateRange(start, end, "coarse")


def describe(dates: DateRange | None) -> str | None:
    """A date range in plain English: "26–29 May 2026", "26 Aug 2026".

    Composed from the parsed dates rather than translated from the French.
    We already know what the notice says structurally; rendering that in
    English is exact, whereas translating prose is a guess — and the French
    original stays alongside as the quotable source.
    """
    if dates is None:
        return None
    start, end = dates.start, dates.end

    def day(value) -> str:
        return f"{value.day} {MONTH_EN[value.month - 1]} {value.year}"

    if start and end:
        if start.date() == end.date():
            return day(start)
        if (start.year, start.month) == (end.year, end.month):
            return f"{start.day}–{end.day} {MONTH_EN[start.month - 1]} {start.year}"
        if start.year == end.year:
            return (
                f"{start.day} {MONTH_EN[start.month - 1]} – "
                f"{end.day} {MONTH_EN[end.month - 1]} {start.year}"
            )
        return f"{day(start)} – {day(end)}"
    if end:
        return f"until {day(end)}"
    if start:
        return f"from {day(start)}"
    return None
