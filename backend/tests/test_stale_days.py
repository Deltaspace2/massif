"""Shelf life per source, and per statement type within a source.

STALE_DAYS answers "how long does this KIND of notice keep" and is right for
notices that are published on a date and then stop being news. Some sources
instead maintain a standing state meant to hold until someone edits it, and
judging those by an arrêté's ninety days calls them old for the sake of it.

The per-type form exists because the source-wide form is a blunt instrument:
applied to a source that publishes both seasons and closures, it would keep a
closure alive for as long as a season.
"""

from massif.enums import StatementType
from massif.status import SOURCE_STALE_DAYS, STALE_DAYS, stale_days_for


class _Statement:
    def __init__(self, statement_type):
        self.statement_type = statement_type
        self.source_id = "s1"


class _Session:
    def __init__(self, slug):
        self.slug = slug

    def scalar(self, _query):
        return self.slug


def test_a_source_wide_entry_covers_every_type_it_publishes():
    """refuges.info's `etat` is a standing wiki field with no date of its own,
    so everything it says ages on the same clock."""
    assert SOURCE_STALE_DAYS["refuges-info"] == 365
    for kind in (StatementType.CLOSURE, StatementType.RESTRICTION):
        assert stale_days_for(_Statement(kind), _Session("refuges-info")) == 365


def test_a_per_type_entry_applies_only_to_the_type_it_names():
    """FFCAM's warden season is fetched weekly and rarely changes, so
    observed_at stays pinned to the day we first saw it and OPENING's thirty
    days would call a current season old in the middle of itself.

    The closure assertion is the point of the per-type form: should this source
    ever publish one, it must age like a closure and not inherit the season's
    240 days."""
    session = _Session("ffcam-refuges")
    assert stale_days_for(_Statement(StatementType.OPENING), session) == 240
    assert stale_days_for(_Statement(StatementType.CLOSURE), session) == STALE_DAYS["closure"]


def test_a_source_with_no_entry_falls_through_to_its_statement_type():
    session = _Session("mairie-saint-gervais")
    assert stale_days_for(_Statement(StatementType.CLOSURE), session) == STALE_DAYS["closure"]
    assert stale_days_for(_Statement(StatementType.OPENING), session) == STALE_DAYS["opening"]
