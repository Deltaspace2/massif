"""Re-extraction over stored history, which had no test at all.

The bug this file was written for: `documents` is immutable and never
deleted, so one weekly URL has one document per fetch. Re-extraction retires
by `document_id` — right, because an improved parser can emit fewer
statements than before and those orphans have no successor — and then wrote
one LIVE statement per historical fetch. The Abri Simond's "cabane non
gardée" stood three times over and /hut/abri-simond, the page Google
indexes, printed it five times.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from massif.scripts import reextract


class _Doc:
    def __init__(self, when: datetime) -> None:
        self.id = uuid.uuid4()
        self.url = "https://example.invalid/api/bbox"
        self.fetched_at = when
        self.extracted_at = None
        self.extraction_error = None


class _Source:
    id = uuid.uuid4()
    slug = "fake-source"


class _Rows(list):
    """session.scalars() is iterated in one place and `.all()`ed in another."""

    def all(self):
        return list(self)


class _Session:
    """Answers by what is being asked for, and records the order of writes."""

    def __init__(self, documents, live=None):
        self.documents = documents
        self.live = list(live or [])
        self.added: list = []
        self.events: list[tuple[str, object]] = []

    def scalar(self, _q):
        return _Source

    def scalars(self, query):
        target = str(query)
        if "documents" in target:
            return _Rows(self.documents)
        return _Rows(self.live)

    def add(self, obj):
        self.added.append(obj)
        self.events.append(("add", obj))

    def flush(self):
        pass


class _Made:
    """What resolve_and_build hands back — one statement per document."""

    def __init__(self, document):
        self.id = uuid.uuid4()
        self.document_id = document.id
        self.feature_id = uuid.uuid4()
        self.superseded_at = None


@pytest.fixture
def wired(monkeypatch):
    """Enough of the world for main() to run with no database."""
    documents = [
        _Doc(datetime(2026, 8, 18, tzinfo=UTC)),
        _Doc(datetime(2026, 8, 25, tzinfo=UTC)),
        _Doc(datetime(2026, 9, 1, tzinfo=UTC)),
    ]
    session = _Session(documents)

    class _Scope:
        def __enter__(self):
            return session

        def __exit__(self, *_):
            return False

    class _Scraper:
        def extract_stored(self, document):
            return ["one reading"]

        def resolve_and_build(self, _session, _source, document, _item, _resolver):
            return _Made(document)

    monkeypatch.setattr(reextract, "session_scope", lambda: _Scope())
    monkeypatch.setattr(reextract, "SCRAPERS", {"fake-source": _Scraper})
    monkeypatch.setattr(reextract, "FeatureResolver", lambda _s: object())
    monkeypatch.setattr(reextract, "recompute_many", lambda *a, **k: None)
    monkeypatch.setattr(reextract, "lift_undated_closures", lambda *a, **k: 0)
    return session, documents


def test_a_later_fetch_of_the_same_page_stands_down_the_earlier_reading(wired, monkeypatch):
    """Three stored fetches of one URL must not leave three live statements.

    Retiring by document alone cannot see this: each fetch is its own
    document, so nothing in that loop relates them. `retire_replaced` is the
    rule that does — same feature, same source, same type, overlapping
    validity — and it is what an ingest run has always applied.
    """
    session, _ = wired
    seen: list = []
    monkeypatch.setattr(
        reextract, "retire_replaced", lambda _s, statement: (seen.append(statement), 1)[1]
    )
    assert reextract.main(["reextract", "fake-source"]) == 0
    assert len(session.added) == 3
    assert seen == session.added, "every written statement must be offered for supersession"


def test_supersession_is_decided_before_the_statement_is_in_the_table(wired, monkeypatch):
    """Order is the whole guard.

    `retire_replaced` looks for live statements this one replaces. Called
    AFTER session.add, the incoming statement is among them and its own
    observed_at is not greater than itself — so it supersedes itself and the
    feature loses the reading that was meant to win.
    """
    session, _ = wired

    def spy(_s, statement):
        session.events.append(("retire", statement))
        return 0

    monkeypatch.setattr(reextract, "retire_replaced", spy)
    reextract.main(["reextract", "fake-source"])
    for index, (kind, obj) in enumerate(session.events):
        if kind == "add":
            assert session.events[index - 1] == ("retire", obj), (
                "retire_replaced must run before the statement it belongs to is added"
            )


def test_documents_are_re_read_oldest_first(wired):
    """`retire_replaced` leaves the newer reading alone and stands the older
    one down, so the order documents are replayed in decides which survives.
    Newest-first would retire the newest and publish the stalest."""
    _, documents = wired
    import inspect

    source = inspect.getsource(reextract.main)
    assert ".order_by(Document.fetched_at)" in source
    assert documents == sorted(documents, key=lambda d: d.fetched_at)
