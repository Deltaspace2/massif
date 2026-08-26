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

import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, time as dtime

MONTHS: dict[str, int] = {
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "aout": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12,
}

_MONTH_ALT = "|".join(MONTHS)
_DAY = r"(\d{1,2})(?:\s*er)?"


def strip_accents(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c))


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", strip_accents(text).lower()).strip()


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
    ("full_range", re.compile(
        rf"du\s+{_DAY}\s+({_MONTH_ALT})\s+(\d{{4}})\s+au\s+{_DAY}\s+({_MONTH_ALT})\s+(\d{{4}})")),
    ("split_month", re.compile(
        rf"du\s+{_DAY}\s+({_MONTH_ALT})\s+au\s+{_DAY}\s+({_MONTH_ALT})\s+(\d{{4}})")),
    ("same_month", re.compile(
        rf"du\s+{_DAY}\s+au\s+{_DAY}\s+({_MONTH_ALT})\s+(\d{{4}})")),
    ("numeric_range", re.compile(
        r"du\s+(\d{1,2})/(\d{1,2})/(\d{2,4})\s+au\s+(\d{1,2})/(\d{1,2})/(\d{2,4})")),
    ("until", re.compile(
        rf"jusqu'?\s*au\s+{_DAY}\s+({_MONTH_ALT})\s+(\d{{4}})")),
    ("from", re.compile(
        rf"a\s+partir\s+du\s+{_DAY}\s+({_MONTH_ALT})\s+(\d{{4}})")),
    ("single_named", re.compile(
        rf"(?:le|du)\s+{_DAY}\s+({_MONTH_ALT})\s+(\d{{4}})")),
    ("single_numeric", re.compile(
        r"le\s+(\d{1,2})/(\d{1,2})/(\d{2,4})")),
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
            if rule == "until":
                day, month, year = groups
                return DateRange(None, _at(_year(year), MONTHS[month], int(day), end=True), rule)
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
