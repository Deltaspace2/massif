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

_MONTH_ALT = "|".join(MONTHS)
_DAY = r"(\d{1,2})(?:\s*er)?"


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
_WEEKDAYS = re.compile(r"\b(lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)\b")


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


# Ordered most specific first: "du 28 décembre 2026 au 3 janvier 2027" also
# contains a substring matching the same-month pattern.
_PATTERNS: list[tuple[str, re.Pattern]] = [
    (
        "full_range",
        re.compile(
            rf"du\s+{_DAY}\s+({_MONTH_ALT})\s+(\d{{4}})\s+au\s+{_DAY}\s+({_MONTH_ALT})\s+(\d{{4}})"
        ),
    ),
    (
        "split_month",
        re.compile(rf"du\s+{_DAY}\s+({_MONTH_ALT})\s+au\s+{_DAY}\s+({_MONTH_ALT})\s+(\d{{4}})"),
    ),
    ("same_month", re.compile(rf"du\s+{_DAY}\s+au\s+{_DAY}\s+({_MONTH_ALT})\s+(\d{{4}})")),
    (
        "numeric_range",
        re.compile(r"du\s+(\d{1,2})/(\d{1,2})/(\d{2,4})\s+au\s+(\d{1,2})/(\d{1,2})/(\d{2,4})"),
    ),
    # "du 26 mai 2026 et jusqu'au 29 mai 2026" — both ends stated, but not in
    # the "du X au Y" shape full_range wants. Real, and from an arrêté: before
    # this it fell through to `until` and lost its start date.
    (
        "from_until",
        re.compile(
            rf"du\s+{_DAY}\s+({_MONTH_ALT})\s+(\d{{4}})[^0-9]{{0,24}}?"
            rf"jusqu'?\s*au\s+{_DAY}\s+({_MONTH_ALT})\s+(\d{{4}})"
        ),
    ),
    # "du 12 juin au soir, jusqu'au 8 septembre 2026" — both ends stated, only
    # the second carrying a year. The first takes the second's year, which is
    # the only reading that is not a range ending before it starts.
    (
        "from_until_split",
        re.compile(
            rf"du\s+{_DAY}\s+({_MONTH_ALT})\b[^0-9]{{0,24}}?"
            rf"jusqu'?\s*au\s+{_DAY}\s+({_MONTH_ALT})\s+(\d{{4}})"
        ),
    ),
    ("until", re.compile(rf"jusqu'?\s*au\s+{_DAY}\s+({_MONTH_ALT})\s+(\d{{4}})")),
    # The numeric forms of the same two shapes. Hut websites write "gardé
    # jusqu'au 30/08" where a mairie writes "jusqu'au 30 août 2026", and the
    # named-month rules above could not see them at all.
    ("until_numeric", re.compile(r"jusqu'?\s*au\s+(\d{1,2})/(\d{1,2})/(\d{2,4})")),
    ("from_numeric", re.compile(r"(?:a\s+partir\s+du|des\s+le)\s+(\d{1,2})/(\d{1,2})/(\d{2,4})")),
    ("from", re.compile(rf"a\s+partir\s+du\s+{_DAY}\s+({_MONTH_ALT})\s+(\d{{4}})")),
    ("single_named", re.compile(rf"(?:le|du)\s+{_DAY}\s+({_MONTH_ALT})\s+(\d{{4}})")),
    ("single_numeric", re.compile(r"le\s+(\d{1,2})/(\d{1,2})/(\d{2,4})")),
]


def parse_range(text: str) -> DateRange | None:
    """First matching rule wins. Returns None when no date is present at all —
    which is a normal outcome, not a failure: most municipal news has no dates."""
    flat = _norm(text)

    for rule, pattern in _PATTERNS:
        match = pattern.search(flat)
        if not match:
            continue
        groups = match.groups()

        try:
            if rule == "full_range":
                d1, m1, y1, d2, m2, y2 = groups
                return DateRange(
                    _at(_year(y1), MONTHS[m1], int(d1)),
                    _at(_year(y2), MONTHS[m2], int(d2), end=True),
                    rule,
                )
            if rule == "split_month":
                d1, m1, d2, m2, year = groups
                # A range crossing New Year is written with both years, so it
                # matches full_range above; here both months share one year.
                return DateRange(
                    _at(_year(year), MONTHS[m1], int(d1)),
                    _at(_year(year), MONTHS[m2], int(d2), end=True),
                    rule,
                )
            if rule == "same_month":
                d1, d2, month, year = groups
                return DateRange(
                    _at(_year(year), MONTHS[month], int(d1)),
                    _at(_year(year), MONTHS[month], int(d2), end=True),
                    rule,
                )
            if rule == "numeric_range":
                d1, m1, y1, d2, m2, y2 = groups
                return DateRange(
                    _at(_year(y1), int(m1), int(d1)),
                    _at(_year(y2), int(m2), int(d2), end=True),
                    rule,
                )
            if rule == "from_until":
                d1, m1, y1, d2, m2, y2 = groups
                return DateRange(
                    _at(_year(y1), MONTHS[m1], int(d1)),
                    _at(_year(y2), MONTHS[m2], int(d2), end=True),
                    rule,
                )
            if rule == "from_until_split":
                d1, m1, d2, m2, year = groups
                start = _at(_year(year), MONTHS[m1], int(d1))
                end = _at(_year(year), MONTHS[m2], int(d2), end=True)
                if start > end:
                    # A season stated across new year: the start belongs to the
                    # year before the one the end names.
                    start = _at(_year(year) - 1, MONTHS[m1], int(d1))
                return DateRange(start, end, rule)
            if rule == "until":
                day, month, year = groups
                return DateRange(None, _at(_year(year), MONTHS[month], int(day), end=True), rule)
            if rule == "until_numeric":
                day, month, year = groups
                return DateRange(None, _at(_year(year), int(month), int(day), end=True), rule)
            if rule == "from_numeric":
                day, month, year = groups
                return DateRange(_at(_year(year), int(month), int(day)), None, rule)
            if rule == "from":
                day, month, year = groups
                return DateRange(_at(_year(year), MONTHS[month], int(day)), None, rule)
            if rule == "single_named":
                day, month, year = groups
                start = _at(_year(year), MONTHS[month], int(day))
                return DateRange(start, _at(_year(year), MONTHS[month], int(day), end=True), rule)
            if rule == "single_numeric":
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
    found = _COARSE_END.findall(_norm(text))
    if len(found) != 2:
        return None

    ends = []
    for index, (day, word, month, explicit_year) in enumerate(found):
        if not day and not word:
            return None  # a bare month name is not a date
        month_number = MONTHS[month]
        on = int(explicit_year) if explicit_year else year
        number = int(day) if day else QUALIFIERS[word][1 if index == 0 else 0]
        number = min(number, _last_day(on, month_number))
        ends.append((on, month_number, number))

    (y1, m1, d1), (y2, m2, d2) = ends
    start = datetime(y1, m1, d1, tzinfo=UTC)
    end = datetime(y2, m2, d2, 23, 59, 59, tzinfo=UTC)
    if start >= end:
        if not may_cross_year or explicit_year:
            return None
        # September to February is next February. Only when the phrase did not
        # state its own year: a source that wrote both years and still ran
        # backwards has said something we do not understand, and guessing at
        # it is worse than queueing it.
        end = datetime(y2 + 1, m2, d2, 23, 59, 59, tzinfo=UTC)
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
