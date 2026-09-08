"""A source that stops listing a feature has said something, and it is not silence.

`retire_replaced` retires an old reading when a NEW one arrives for the same
feature and source. A source that simply drops a feature never sends that
successor, so nothing retires and the last thing it ever said stands for ever.
Six Megève features were dropped from `mbnr-live` when the ski season ended and
sat frozen on *"close — départ toutes les 30 mn à partir de 9h"* into
September, 31.8 hours past their last mention and still rendering.

TWO THINGS THIS MUST NOT DO, and both fail unsafe:

* **Retire on absence from a source that does not enumerate.** Only a source
  where one fetch lists everything it speaks about can have absence read as
  evidence. `mairie-saint-gervais` caps at `MAX_ARTICLES`, so absence there can
  be *our own cap* rather than the mairie's silence — retiring on it would drop
  a still-valid arrêté and turn a shut route UNKNOWN. Hence opt-in, per source.

* **Retire on elapsed time.** A feed that omits a feature for one run because
  of a partial outage must keep it. The unit is successful runs.

The whole mechanism rests on `confirm_still_standing` (see its own test file)
advancing `last_seen_at` on every run that DID mention a statement, unchanged
pages included. Every successful run after that timestamp is then, by
definition, a run that asked and did not say it — so one mention resets the
count with no counter to keep. Before that fix, this would have retired
everything from any source whose pages sit still.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from massif.ingest.base import retire_unmentioned

NOW = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)


def ago(hours: float) -> datetime:
    return NOW - timedelta(hours=hours)


class _Statement:
    def __init__(self, last_seen: datetime) -> None:
        self.id = uuid.uuid4()
        self.feature_id = uuid.uuid4()
        self.last_seen_at = last_seen
        self.superseded_at = None
        self.superseded_by = None


class _Source:
    def __init__(self, config=None) -> None:
        self.id = uuid.uuid4()
        self.slug = "fake-source"
        self.fetch_config = config


class _Rows(list):
    def all(self):
        return list(self)


class _Session:
    """Answers by what is asked for: statements, or run start times."""

    def __init__(self, live, run_starts):
        self.live = list(live)
        self.run_starts = list(run_starts)
        self.queries: list = []

    def scalars(self, query):
        self.queries.append(query)
        text = str(query).lower()
        if "ingest_runs" in text:
            ordered = sorted(self.run_starts, reverse=True)
            limit = query._limit if query._limit is not None else len(ordered)
            return _Rows(ordered[:limit])
        return _Rows(self.live)


OPTED_IN = {"retire_after_unmentioned_runs": 3}


def _runs(*hours_ago: float) -> list[datetime]:
    return [ago(h) for h in hours_ago]


# ------------------------------------------------------------------- opt-in


def test_a_source_that_has_not_opted_in_retires_nothing():
    """The default, and the safe one. Every source but `mbnr-live` is here."""
    stale = _Statement(ago(500))
    session = _Session([stale], _runs(1, 4, 7, 10))
    assert retire_unmentioned(session, _Source(None), NOW) == []
    assert stale.superseded_at is None


def test_an_empty_config_is_also_opted_out():
    stale = _Statement(ago(500))
    assert retire_unmentioned(_Session([stale], _runs(1, 4, 7)), _Source({}), NOW) == []
    assert stale.superseded_at is None


def test_a_config_with_other_keys_but_not_this_one_is_opted_out():
    """`fetch_config` also carries notes and licence. Reading truthiness of the
    dict rather than of the key would opt in every source that has a licence."""
    config = {"notes": "...", "licence": "CC BY-SA 2.0"}
    stale = _Statement(ago(500))
    assert retire_unmentioned(_Session([stale], _runs(1, 4, 7)), _Source(config), NOW) == []
    assert stale.superseded_at is None


# --------------------------------------------------------- counting in runs


def test_a_statement_missed_by_n_successful_runs_is_retired():
    """Megève: last mentioned 31.8h ago, asked ten times since."""
    megeve = _Statement(ago(31.8))
    session = _Session([megeve], _runs(0.3, 3, 6, 9, 12, 15, 18, 24, 30))

    retired = retire_unmentioned(session, _Source(OPTED_IN), NOW)

    assert retired == [megeve]
    assert megeve.superseded_at == NOW
    # No successor exists, so nothing for superseded_by to point at — the same
    # shape re-extraction orphans already have.
    assert megeve.superseded_by is None


def test_a_statement_mentioned_in_the_latest_run_survives():
    """`confirm_still_standing` moved its clock, so no run has asked since."""
    current = _Statement(ago(0.2))
    session = _Session([current], _runs(0.3, 3, 6, 9, 12))
    assert retire_unmentioned(session, _Source(OPTED_IN), NOW) == []
    assert current.superseded_at is None


def test_one_missed_run_is_not_enough():
    """A partial outage must not retire anything. Threshold is 3; this
    statement was mentioned before the second-most-recent run."""
    blipped = _Statement(ago(2))
    session = _Session([blipped], _runs(0.3, 3, 6, 9))
    assert retire_unmentioned(session, _Source(OPTED_IN), NOW) == []
    assert blipped.superseded_at is None


def test_two_missed_runs_is_still_not_enough():
    """The boundary, from the safe side. Missed by the runs at 0.3h and 3h,
    but mentioned after the one at 6h."""
    survivor = _Statement(ago(5))
    session = _Session([survivor], _runs(0.3, 3, 6, 9))
    assert retire_unmentioned(session, _Source(OPTED_IN), NOW) == []


def test_exactly_three_missed_runs_retires():
    """The same boundary from the other side: one hour older, and the run at
    6h has now asked too."""
    goner = _Statement(ago(7))
    session = _Session([goner], _runs(0.3, 3, 6, 9))
    assert retire_unmentioned(session, _Source(OPTED_IN), NOW) == [goner]


def test_only_successful_runs_count():
    """A run that failed did not ask. The query filters on `ok`, so a session
    that reports no successful runs must retire nothing however old the
    statement is — otherwise a broken scraper would quietly empty the map."""
    stale = _Statement(ago(500))
    session = _Session([stale], [])  # no successful runs at all
    assert retire_unmentioned(session, _Source(OPTED_IN), NOW) == []
    assert stale.superseded_at is None
    where = str(session.queries[-1].whereclause).lower()
    assert "ok" in where


def test_a_database_without_enough_history_retires_nothing():
    """Fewer successful runs than the threshold means we have not asked N
    times yet. A fresh database must not retire its seed data on run one."""
    stale = _Statement(ago(500))
    session = _Session([stale], _runs(0.3, 3))
    assert retire_unmentioned(session, _Source(OPTED_IN), NOW) == []


# -------------------------------------------------- what it asks the database


def test_it_considers_only_this_source_and_only_live_statements():
    session = _Session([], _runs(0.3, 3, 6, 9))
    retire_unmentioned(session, _Source(OPTED_IN), NOW)

    # The statements query is the first one issued.
    where = str(session.queries[0].whereclause).lower()
    assert "source_id" in where
    assert where.count("superseded_at is null") == 1
    assert where.count("superseded_by is null") == 1


def test_it_counts_runs_by_when_they_started_not_when_they_finished():
    """The off-by-one that would break everything quietly.

    `finished_at` is set after statements are written, so it is later than the
    `last_seen_at` of the very statements that run produced — every fresh
    statement would show a miss the moment it was born, and a source would
    retire its own output after three runs. `started_at` precedes the write.
    """
    # A live statement, or the function short-circuits before it ever asks
    # about runs, and this asserts against the wrong query.
    session = _Session([_Statement(ago(0.2))], _runs(0.3, 3, 6))
    retire_unmentioned(session, _Source(OPTED_IN), NOW)

    runs_query = str(session.queries[-1]).lower()
    assert "ingest_runs" in runs_query, "asserted against the wrong query"
    assert "started_at" in runs_query
    assert "finished_at" not in runs_query


def test_a_mixed_batch_retires_only_the_forgotten_ones():
    """The real shape of a Megève run: most lifts re-emitted, five not."""
    kept = [_Statement(ago(0.2)) for _ in range(4)]
    dropped = [_Statement(ago(31.8)) for _ in range(5)]
    session = _Session([*kept, *dropped], _runs(0.3, 3, 6, 9, 12))

    retired = retire_unmentioned(session, _Source(OPTED_IN), NOW)

    assert len(retired) == 5
    assert all(st.superseded_at == NOW for st in dropped)
    assert all(st.superseded_at is None for st in kept)
