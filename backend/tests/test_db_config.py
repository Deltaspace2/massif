"""The pooler switch is configuration that only misbehaves under concurrency
in production, which is the least useful place to discover it. Pin it here.
"""

from __future__ import annotations

import pytest
from sqlalchemy.pool import NullPool

from massif import db
from massif.config import Settings

DIRECT = "postgresql+psycopg://massif:massif@localhost:5432/massif"
SESSION_POOLER = "postgresql+psycopg://u:p@aws-0-eu-west-3.pooler.supabase.com:5432/postgres"
TRANSACTION_POOLER = "postgresql+psycopg://u:p@aws-0-eu-west-3.pooler.supabase.com:6543/postgres"
PGBOUNCER = "postgresql+psycopg://u:p@db.example.org:5432/massif?pgbouncer=true"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (DIRECT, False),
        # Session mode gives each client its own backend for the life of the
        # connection, so prepared statements are safe. Only :6543 is not.
        (SESSION_POOLER, False),
        (TRANSACTION_POOLER, True),
        (PGBOUNCER, True),
    ],
)
def test_pooling_is_inferred_from_the_url(url: str, expected: bool) -> None:
    assert Settings(database_url=url, database_pooled=None).pooled is expected


@pytest.mark.parametrize("url", [DIRECT, TRANSACTION_POOLER])
@pytest.mark.parametrize("override", [True, False])
def test_explicit_setting_beats_the_guess(url: str, override: bool) -> None:
    assert Settings(database_url=url, database_pooled=override).pooled is override


def test_direct_connections_keep_the_default_pool(monkeypatch) -> None:
    monkeypatch.setattr(db, "settings", Settings(database_url=DIRECT))
    kwargs = db.engine_kwargs()
    assert kwargs == {"pool_pre_ping": True}


def test_a_transaction_pooler_disables_prepared_statements(monkeypatch) -> None:
    """Both halves matter. Without NullPool the function holds pooler slots it
    cannot use; without prepare_threshold=None psycopg names a prepared
    statement the next backend has never seen."""
    monkeypatch.setattr(db, "settings", Settings(database_url=TRANSACTION_POOLER))
    kwargs = db.engine_kwargs()
    assert kwargs["poolclass"] is NullPool
    assert kwargs["connect_args"]["prepare_threshold"] is None
    assert "pool_pre_ping" not in kwargs
