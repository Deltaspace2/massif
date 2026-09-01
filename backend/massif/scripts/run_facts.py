"""Run every directory-facts importer that is due.

    python -m massif.scripts.run_facts            # all due
    python -m massif.scripts.run_facts --force    # ignore the cadence

WHY THIS EXISTS SEPARATELY FROM run_ingest. Facts are not statements, so they
do not go through the scraper registry, the document store or the status
pipeline — a bunk count is a property of a building, not a claim in force over
a window. But they still need fetching on a schedule, and until now nothing
fetched them: both importers were things a human ran by hand, which meant a
deployed site would have shown whatever facts happened to be in the database on
the day it launched, for ever.

Each importer carries its own cadence in the data rather than in the cron —
they exit without fetching unless their last pull is older than a week — so the
hourly workflow calls this every hour and it does nothing 167 times out of 168.
That is deliberate: the schedule is a ceiling, and the source's own interval is
the real control.

Exits non-zero if any importer failed, so a broken one shows up as a red run
rather than quietly rotting. Silence is this project's real failure mode.
"""

from __future__ import annotations

import sys

from massif.scripts import import_camptocamp_facts, import_hut_facts

IMPORTERS = {
    "refuges-info": import_hut_facts.main,
    "camptocamp": import_camptocamp_facts.main,
}


def main(argv: list[str]) -> int:
    force = "--force" in argv[1:]
    failures = 0

    for slug, entry in IMPORTERS.items():
        print(f"[{slug}] facts ...")
        # Each importer parses its own argv, so hand it exactly the flags it
        # understands rather than passing ours through.
        saved = sys.argv
        sys.argv = [slug, "--apply"] + (["--force"] if force else [])
        try:
            code = entry()
            if code:
                failures += 1
                print(f"[{slug}] FAILED (exit {code})", file=sys.stderr)
        except Exception as exc:
            failures += 1
            print(f"[{slug}] FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        finally:
            sys.argv = saved

    if failures:
        print(f"\n{failures} facts importer(s) failed", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
