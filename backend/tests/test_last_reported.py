"""Showing what a source used to say, without it reading as a status.

`retire_unmentioned` retires a statement when its source has stopped listing
the feature. That is right — the claim is not current and must not hold a
status slot — but it left the feature page saying "no source this site watches
has published anything about this", which for a lift dropped at the end of the
season is false. A source published about it, repeatedly, and then went quiet.

THE DANGEROUS CASE IS `open`, not `closed`. Megève's withdrawn readings all say
closed, which fails safe and makes any wording look fine. The mechanism will
eventually retire an open lift mid-season, and "last reported open" is exactly
the stale-open-reading-as-clearance failure this site exists to avoid. So the
sentence is built to lead with the withdrawal rather than the status word, and
the status appears only inside a dated quotation.

The narrowing is the other half. Three different things set `superseded_at`
with `superseded_by` left null — an ordinary replacement, a re-extraction
retraction, and this — and only the last is worth repeating to a reader. The
first has a successor already on the page; the second is a claim we decided was
wrong, and republishing it would be publishing something we disbelieve.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from massif.enums import StatusValue
from massif.main import _last_reported

SEEN = datetime(2026, 9, 6, 23, 26, tzinfo=UTC)
PUBLISHED = datetime(2026, 9, 6, 23, 20, tzinfo=UTC)
RETIRED = datetime(2026, 9, 8, 7, 24, tzinfo=UTC)


@dataclass
class FakeStatement:
    status: StatusValue = StatusValue.CLOSED
    summary_en: str | None = "Megève - Rochebrune - 1750 m: all 2 lifts closed"
    observed_at: datetime | None = PUBLISHED
    last_seen_at: datetime | None = SEEN
    superseded_at: datetime | None = RETIRED
    retired_reason: str | None = "unmentioned"


@dataclass
class FakeSource:
    name: str = "Mont-Blanc Natural Resort — live lift status"
    url: str = "https://www.montblancnaturalresort.com/fr/infos-live"


@dataclass
class FakeStatus:
    status: StatusValue = StatusValue.UNKNOWN


@dataclass
class FakeSession:
    """Returns one row, and keeps the query so the filters can be inspected."""

    row: tuple | None = None
    queries: list = field(default_factory=list)

    def execute(self, query):
        self.queries.append(query)
        session = self

        class _Result:
            def first(self):
                return session.row

        return _Result()


FEATURE = uuid.uuid4()


# ------------------------------------------------------------ when it shows


def test_it_shows_a_withdrawn_reading_where_there_is_no_current_status():
    session = FakeSession(row=(FakeStatement(), FakeSource()))
    got = _last_reported(session, FEATURE, FakeStatus(StatusValue.UNKNOWN))
    assert got is not None
    assert got["status"] is StatusValue.CLOSED
    assert got["observed_at"] == PUBLISHED
    assert got["last_seen_at"] == SEEN
    assert got["retired_at"] == RETIRED


def test_a_feature_with_no_status_row_at_all_still_gets_one():
    """`recompute` leaves no FeatureStatus for a feature nothing has ever been
    said about — and a feature whose only source went quiet can be in exactly
    that state."""
    session = FakeSession(row=(FakeStatement(), FakeSource()))
    assert _last_reported(session, FEATURE, None) is not None


def test_it_carries_the_attribution():
    """The reader is being shown someone else's sentence, and needs to know
    whose — and where to go now that we cannot answer."""
    session = FakeSession(row=(FakeStatement(), FakeSource()))
    got = _last_reported(session, FEATURE, FakeStatus())
    assert got["source"]["name"] == "Mont-Blanc Natural Resort — live lift status"
    assert got["source"]["url"].startswith("https://")


# -------------------------------------------------------- when it must not


def test_it_is_silent_where_a_status_exists():
    """Beside a live status from another source this reads as a competing
    claim, and the page would be showing two answers to one question."""
    session = FakeSession(row=(FakeStatement(), FakeSource()))
    for live in (StatusValue.OPEN, StatusValue.CLOSED, StatusValue.RESTRICTED,
                 StatusValue.UNSTAFFED):
        assert _last_reported(session, FEATURE, FakeStatus(live)) is None


def test_it_does_not_even_ask_when_a_status_exists():
    """Not merely that the answer is discarded — the query must not run. A
    feature page is the SEO surface and this would be a per-request round trip
    for something that is thrown away."""
    session = FakeSession(row=(FakeStatement(), FakeSource()))
    _last_reported(session, FEATURE, FakeStatus(StatusValue.OPEN))
    assert session.queries == []


def test_nothing_withdrawn_means_nothing_shown():
    assert _last_reported(FakeSession(row=None), FEATURE, FakeStatus()) is None


def test_it_asks_only_for_unmentioned_retirements():
    """The narrowing that keeps a retracted claim off the page.

    An ordinary replacement and a re-extraction retraction both leave
    `superseded_at` set and `superseded_by` null, exactly like this. Filtering
    on that shape instead of on the reason would republish a sentence a better
    parser withdrew, which is worse than saying nothing.
    """
    session = FakeSession(row=None)
    _last_reported(session, FEATURE, FakeStatus())

    where = str(session.queries[0].whereclause).lower()
    assert "retired_reason" in where
    assert "feature_id" in where


# ------------------------------------------------- the wording's safety net


def test_the_summary_is_returned_as_stored_and_never_re_tensed():
    """`phrase_for_now` moves a claim toward the present. This one is going the
    other way: it is quoted past reporting, and re-tensing it would produce a
    present-tense sentence about a lift nobody is reporting on."""
    stored = "TC PRARION: open — départ toutes les 30 mn à partir de 9h"
    session = FakeSession(row=(FakeStatement(summary_en=stored), FakeSource()))
    got = _last_reported(session, FEATURE, FakeStatus())
    assert got["summary"] == stored


def test_a_withdrawn_open_reading_still_carries_both_dates():
    """The `open` case, which is the one that can hurt.

    The rendered sentence quotes the claim and leans on these two dates to make
    it read as history — when the source published it, and when we last found
    it. A withdrawn "open" with no date beside it is clearance.
    """
    session = FakeSession(
        row=(FakeStatement(status=StatusValue.OPEN, summary_en="TPH BELLEVUE: open"), FakeSource())
    )
    got = _last_reported(session, FEATURE, FakeStatus())
    assert got["status"] is StatusValue.OPEN
    assert got["observed_at"] is not None, "an undated withdrawn open reads as clearance"
    assert got["last_seen_at"] is not None
