"""Rules every migration file has to keep.

migrate.py is deliberately dumb: it reads db/migrations/*.sql in filename
order, runs each one it has not seen, and prints ok. It does NOT record that a
migration ran — each file registers itself. 0008 and 0009 were both written
without that line, so they applied cleanly, printed ok, and then failed on the
next run against a database that already had their changes. The failure
surfaces one run late, on someone else's machine, which is the worst place for
it. Enforced here instead of remembered.
"""

import re
from pathlib import Path

import pytest

MIGRATIONS = Path(__file__).resolve().parents[2] / "db" / "migrations"
FILES = sorted(MIGRATIONS.glob("*.sql"))


def test_there_are_migrations_to_check():
    assert FILES, f"no .sql files under {MIGRATIONS}"


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_every_migration_registers_itself(path: Path):
    sql = path.read_text(encoding="utf-8")
    assert "INSERT INTO schema_migrations" in sql, (
        f"{path.name} never records itself, so migrate.py will re-run it "
        "forever and fail the moment its changes already exist"
    )
    assert path.stem in sql, (
        f"{path.name} registers a version string that is not its own filename"
    )


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_every_migration_is_one_transaction(path: Path):
    """A half-applied migration is worse than a failed one: the schema and the
    record of it disagree, which is how this bug produced a database whose
    column existed but whose version did not."""
    sql = path.read_text(encoding="utf-8")
    assert re.search(r"^\s*BEGIN;", sql, re.M), f"{path.name} does not open a transaction"
    assert re.search(r"^\s*COMMIT;", sql, re.M), f"{path.name} does not commit"


def test_filenames_sort_in_application_order():
    """migrate.py sorts by filename, so a version that sorts wrong runs wrong."""
    numbers = [int(p.stem.split("_")[0]) for p in FILES]
    assert numbers == sorted(numbers)
    assert len(numbers) == len(set(numbers)), "two migrations share a number"
