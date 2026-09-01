"""Run every source that is active, registered, and due.

Entry point for the GitHub Actions cron. Exits non-zero if any source failed,
so a broken scraper shows up as a red run rather than quietly rotting — the
real failure mode of this project is a site that stopped updating while still
looking current.

    python -m massif.scripts.run_ingest            # all due sources
    python -m massif.scripts.run_ingest mbnr-live  # one source, ignoring due
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from massif.db import session_scope
from massif.ingest.registry import SCRAPERS
from massif.models import Source


def is_due(source: Source, now: datetime) -> bool:
    if source.last_fetch_at is None:
        return True
    interval = timedelta(minutes=source.fetch_interval_minutes)
    # exponential backoff on repeated failure, capped at 8x
    if source.consecutive_failures:
        interval *= min(2**source.consecutive_failures, 8)
    return source.last_fetch_at + interval <= now


def main(argv: list[str]) -> int:
    only = set(argv[1:])
    now = datetime.now(UTC)
    failures = 0
    ran = 0
    unbuilt: list[str] = []

    with session_scope() as session:
        sources = session.scalars(select(Source).where(Source.active.is_(True))).all()

        unbuilt[:] = [s.slug for s in sources if s.slug not in SCRAPERS]

        for source in sources:
            if source.slug not in SCRAPERS:
                continue
            if only and source.slug not in only:
                continue
            if not only and not is_due(source, now):
                continue

            print(f"[{source.slug}] running ...")
            try:
                run = SCRAPERS[source.slug]().run(session)
                session.commit()
                print(
                    f"[{source.slug}] ok — {run.documents_new} new documents, "
                    f"{run.statements_new} statements, "
                    f"{run.unresolved_new} unresolved"
                )
                if run.unresolved_new:
                    print(
                        f"[{source.slug}] {run.unresolved_new} names did not "
                        f"resolve — run massif.scripts.review_queue"
                    )
            except Exception as exc:
                session.rollback()
                failures += 1
                print(f"[{source.slug}] FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
            ran += 1

    if not ran:
        print("nothing due")
    if unbuilt:
        print(f"active sources with no scraper yet: {', '.join(unbuilt)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
