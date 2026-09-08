"""An unchanged page still counts as having been checked.

The bug, found 8 Sep 2026. `last_seen_at` is defined by rule 10 as "when we
last fetched and found it still standing", and it lives on the Statement row,
so it only moves when `run()` writes a statement. Five scrapers skipped a
document whose bytes had not changed — `if not is_new: continue` — which meant
they fetched the page, found the notice exactly where it was, and wrote nothing
down.

The Goûter reopening notice was being re-read every six hours and last recorded
seventeen hours earlier. Three stored copies of that article all parse to the
same three statements today, so nothing was withdrawn and nothing broke: the
column simply advanced only when some unrelated part of the page happened to
change. That badged an arrêté-regulated route OVERDUE on a frozen **open**,
which is the direction that fails unsafe.

The fix is a contract, and the contract is the thing worth testing: `collect()`
may return `None` for a document's statements, and `None` is not `[]`.

    []    parsed, contains no notice. Real and common.
    None  unchanged since the copy we hold; not re-parsed; still stands.

Everything here exists to keep those two apart, because the failure mode of
confusing them is silent in both directions — `[]` where `None` belongs freezes
a claim, and `None` where `[]` belongs would keep a withdrawn one alive.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from massif.ingest import base
from massif.ingest.base import Scraper, confirm_still_standing

NOW = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
EARLIER = datetime(2026, 9, 7, 13, 55, tzinfo=UTC)


class _Doc:
    def __init__(self) -> None:
        self.id = uuid.uuid4()
        self.url = "https://example.invalid/actualites/reouverture"
        self.extracted_at = None


class _Statement:
    def __init__(self, feature_id=None) -> None:
        self.id = uuid.uuid4()
        self.feature_id = feature_id or uuid.uuid4()
        self.last_seen_at = EARLIER


class _Rows(list):
    def all(self):
        return list(self)


class _Session:
    """Returns the statements it was given, and keeps the query for inspection."""

    def __init__(self, live):
        self.live = list(live)
        self.queries: list = []
        self.added: list = []
        self.flushed = 0

    def scalars(self, query):
        self.queries.append(query)
        return _Rows(self.live)

    def scalar(self, _query):
        return None

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        self.flushed += 1


# ------------------------------------------------------- the helper itself


def test_it_records_that_the_claim_was_seen_again():
    live = [_Statement(), _Statement()]
    session = _Session(live)

    confirmed = confirm_still_standing(session, _Doc(), NOW)

    assert len(confirmed) == 2
    assert all(st.last_seen_at == NOW for st in live)


def test_it_returns_the_statements_so_their_features_can_be_recomputed():
    """The API reads `last_seen_at` off `feature_status`, not off the
    statement. A refresh without a recompute updates a row nothing renders,
    which looks exactly like the bug it was meant to fix."""
    live = [_Statement(), _Statement()]
    confirmed = confirm_still_standing(_Session(live), _Doc(), NOW)
    assert {st.feature_id for st in confirmed} == {st.feature_id for st in live}


def test_it_asks_only_for_this_document_and_only_for_live_statements():
    """Three filters, and dropping any one is silent.

    Without `document_id` it would refresh the whole source. Without the two
    superseded columns it would resurrect the clock on retired readings — the
    statements `retire_replaced` has already put out of service — and a
    superseded row with a fresh `last_seen_at` is a claim that looks current
    to anything that later forgets to filter.
    """
    session = _Session([])
    confirm_still_standing(session, _Doc(), NOW)

    # The WHERE clause specifically, not the whole statement. `select(Statement)`
    # names every column in its select list, `document_id` among them, so a
    # substring check against the full SQL passes even with the filter deleted —
    # it did, when this was first written.
    where = str(session.queries[0].whereclause).lower()
    assert "document_id" in where
    assert where.count("superseded_at is null") == 1
    assert where.count("superseded_by is null") == 1


def test_nothing_attached_is_not_an_error():
    """A document can legitimately have no live statements — the listing page
    is stored for provenance and carries no notice of its own."""
    assert confirm_still_standing(_Session([]), _Doc(), NOW) == []


# ------------------------------------------- None and [] down different paths


class _Run:
    """IngestRun's counters default at INSERT, and nothing here inserts."""

    def __init__(self, source_id=None) -> None:
        self.source_id = source_id
        self.documents_new = 0
        self.statements_new = 0
        self.unresolved_new = 0
        self.ok = False
        self.error = None
        self.finished_at = None


class _Source:
    id = uuid.uuid4()
    slug = "fake-source"
    language = "fr"
    last_success_at = None
    last_fetch_at = None
    consecutive_failures = 0
    last_error = None


class _RunSession(_Session):
    def scalar(self, _query):
        return _Source


class _Scraper(Scraper):
    slug = "fake-source"

    def __init__(self, payload) -> None:
        self.payload = payload

    def collect(self, session, source):
        return self.payload


@pytest.fixture
def wired(monkeypatch):
    """`run()` with its database neighbours stubbed out."""
    calls: dict = {"confirmed": [], "recomputed": []}

    monkeypatch.setattr(base, "IngestRun", _Run)
    monkeypatch.setattr(base, "FeatureResolver", lambda session: object())
    monkeypatch.setattr(
        base, "recompute_many", lambda session, touched: calls["recomputed"].append(set(touched))
    )

    real = base.confirm_still_standing

    def spy(session, document, now):
        out = real(session, document, now)
        calls["confirmed"].append(document)
        return out

    monkeypatch.setattr(base, "confirm_still_standing", spy)
    return calls


def test_none_confirms_the_document_rather_than_skipping_it(wired):
    document = _Doc()
    live = [_Statement()]
    session = _RunSession(live)

    run = _Scraper([(document, None)]).run(session)

    assert wired["confirmed"] == [document], "an unchanged document must be confirmed"
    assert live[0].last_seen_at != EARLIER, "the clock did not move"
    # And the feature is recomputed, or the refreshed clock never reaches the API.
    assert wired["recomputed"] == [{live[0].feature_id}]
    # Confirming is not ingesting: nothing new was written.
    assert run.documents_new == 0
    assert run.statements_new == 0
    assert session.added == [run]


def test_an_empty_list_is_a_parsed_document_with_no_notice_and_confirms_nothing(wired):
    """The distinction the whole contract rests on.

    A document we read and found no notice in must NOT have its statements
    refreshed — there are none, and if a parser regression started returning
    `[]` where it used to find a closure, treating that as confirmation would
    hold the vanished closure open indefinitely.
    """
    document = _Doc()
    session = _RunSession([_Statement()])

    run = _Scraper([(document, [])]).run(session)

    assert wired["confirmed"] == []
    assert run.documents_new == 1, "it was still a document we fetched and read"
    assert run.statements_new == 0


def test_a_run_can_confirm_some_documents_and_ingest_others(wired):
    """The ordinary shape of a sweep: one article changed, nine did not."""
    changed, unchanged = _Doc(), _Doc()
    session = _RunSession([_Statement()])

    run = _Scraper([(unchanged, None), (changed, [])]).run(session)

    assert wired["confirmed"] == [unchanged]
    assert run.documents_new == 1


def test_the_run_still_succeeds_when_every_document_was_unchanged(wired):
    """A sweep that wrote nothing is a healthy sweep, not a failed one — and
    `last_success_at` must move, or the source looks broken to the scheduler."""
    session = _RunSession([_Statement()])
    run = _Scraper([(_Doc(), None)]).run(session)
    assert run.ok is True
    assert _Source.last_success_at is not None
