"""Apply SQL migrations in db/migrations, in filename order.

Deliberately dumb. Alembic can come later if the schema starts churning;
right now transparent SQL beats generated SQL, especially with PostGIS.
"""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import text

from massif.db import engine

MIGRATIONS = Path(__file__).resolve().parents[3] / "db" / "migrations"


def applied_versions() -> set[str]:
    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT to_regclass('public.schema_migrations')")
        ).scalar()
        if not exists:
            return set()
        return set(conn.scalars(text("SELECT version FROM schema_migrations")))


def main() -> int:
    if not MIGRATIONS.is_dir():
        print(f"no migrations directory at {MIGRATIONS}", file=sys.stderr)
        return 1

    done = applied_versions()
    pending = sorted(
        p for p in MIGRATIONS.glob("*.sql") if p.stem not in done
    )
    if not pending:
        print("up to date")
        return 0

    for path in pending:
        print(f"applying {path.stem} ...", end=" ", flush=True)
        sql = path.read_text(encoding="utf-8")
        with engine.begin() as conn:
            conn.execute(text(sql))
        print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
