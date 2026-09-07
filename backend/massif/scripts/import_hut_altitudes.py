"""Write the hand-sourced altitudes in seeds/hut_altitudes.yaml into features.

    python -m massif.scripts.import_hut_altitudes            # dry run
    python -m massif.scripts.import_hut_altitudes --apply

WHAT IT WILL NOT DO. It sets `alt_max` and appends one sentence to `notes`, on
huts that have NO altitude at all. It never overwrites an altitude — a figure
already in the row came from OSM, from the curated file or from a person, and
all three outrank a number typed from a search result. It never touches
identity: `name_default`, `names`, `aliases` and `country` are not its
business, which is why this is a script of its own rather than nine partial
entries in features_curated.yaml, where the seeder would assign those fields
from rows that do not carry them and blank what the OSM import wrote.

Idempotent by consequence rather than by bookkeeping: once a hut has an
altitude it is skipped, so a second run writes nothing and says so.

The rules that decide whether a row may be written at all live in
`massif/ingest/hut_altitudes.py`, tested without a database.
"""

from __future__ import annotations

import argparse
import sys

import yaml
from sqlalchemy import select

from massif.db import session_scope
from massif.ingest.hut_altitudes import Row, hold_reason, provenance, read_row
from massif.models import Feature
from massif.scripts.seed_features import SEEDS

SEED_FILE = "hut_altitudes.yaml"


def load_rows(path=None) -> list[Row]:
    path = path or SEEDS / SEED_FILE
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return [read_row(entry) for entry in raw]


def ready_rows(rows: list[Row]) -> list[Row]:
    """The rows the evidence allows, printing the reason for the ones it does not.

    Held rows print every single run. The gap is the point: a hut we could not
    source twice is a hut still matched on its name alone, and a line nobody
    sees is a cap nobody knows about.
    """
    ready = []
    for row in rows:
        reason = hold_reason(row)
        if reason is None:
            ready.append(row)
        else:
            print(f"  held {row.slug[:40]:42} {' '.join(reason.split())}")
    return ready


def apply_rows(session, rows: list[Row], apply: bool) -> dict[str, int]:
    """Set alt_max on huts that have none. Takes a session so it can be tested
    without one that talks to Postgres."""
    counts = {"written": 0, "missing": 0, "already": 0}
    for row in rows:
        feature = session.scalar(select(Feature).where(Feature.slug == row.slug))
        if feature is None:
            counts["missing"] += 1
            print(f"  --   {row.slug[:40]:42} no such feature")
            continue
        if feature.alt_max is not None or feature.alt_min is not None:
            counts["already"] += 1
            print(
                f"  --   {row.slug[:40]:42} already holds "
                f"{feature.alt_min or feature.alt_max} m, left alone"
            )
            continue
        hosts = ", ".join(sorted({reading.host for reading in row.readings}))
        print(f"  ok   {row.slug[:40]:42} {row.alt_max:>5} m   {hosts}")
        counts["written"] += 1
        if not apply:
            continue
        feature.alt_max = row.alt_max
        sentence = provenance(row)
        # The OSM importer's note tells the reader that position and altitude
        # both come from OpenStreetMap. For these huts OSM had no altitude, so
        # once one arrives from elsewhere that sentence is wrong on a public
        # page unless this one follows it.
        if sentence not in (feature.notes or ""):
            feature.notes = f"{feature.notes} {sentence}".strip() if feature.notes else sentence
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write; otherwise dry run")
    args = parser.parse_args()

    rows = load_rows()
    ready = ready_rows(rows)

    with session_scope() as session:
        counts = apply_rows(session, ready, args.apply)
        if not args.apply:
            session.rollback()

    print(
        f"\n{len(rows)} rows: {counts['written']} {'written' if args.apply else 'to write'}, "
        f"{len(rows) - len(ready)} held for want of a second source, {counts['already']} "
        f"already had an altitude, {counts['missing']} matched no feature."
    )
    if not args.apply:
        print("dry run — nothing written", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
