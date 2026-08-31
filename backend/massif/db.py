from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from massif.config import settings


def engine_kwargs() -> dict[str, Any]:
    """Engine settings differ behind a transaction pooler, and both
    differences produce failures that read as flaky database errors rather
    than as configuration.

    - SQLAlchemy's own pool is worse than useless in a serverless function
      that may be frozen or discarded between requests: its checked-out
      connections hold pooler slots the next invocation cannot have. NullPool
      hands pooling to the thing whose job it is.
    - psycopg prepares a statement after it has seen it a few times. In
      transaction mode the pooler gives the next statement to a different
      backend, which has never heard of that prepared name. The result is
      InvalidSqlStatementName under load and nothing at all when idle, which
      is the worst possible way to find out.

    Direct connections keep pool_pre_ping: the failure there is a connection
    the database closed while we were not looking, and one round trip is
    cheaper than serving an error.
    """
    if not settings.pooled:
        return {"pool_pre_ping": True}
    return {"poolclass": NullPool, "connect_args": {"prepare_threshold": None}}


engine = create_engine(settings.database_url, future=True, **engine_kwargs())
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    """FastAPI dependency."""
    with session_scope() as session:
        yield session
