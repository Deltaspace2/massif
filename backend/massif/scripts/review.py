"""Clear or throw out the statements a model read.

    python -m massif.scripts.review                    # what is waiting
    python -m massif.scripts.review --show <id>        # one, in full
    python -m massif.scripts.review --accept <id> [--note "..."]
    python -m massif.scripts.review --reject <id> [--note "..."]

`review_queue` is the OTHER queue: names that did not resolve to a feature.
This one is statements that resolved perfectly and are waiting for a person,
because a machine read them out of prose.

WHY A PERSON IS IN THE LOOP AT ALL. llm.py's three automatic guards catch
fabrication — an invented span, a date that disagrees with the phrase it came
from, a feature the model chose itself. None of them catches MISREADING, where
every span is real and correctly quoted and the reading is still wrong. Two
live examples, both from the first day this ran: a journalist's line about
conditions having improved read as "couloir du Goûter: open", and the Rifugio
Torino's page announcing it closes on 11 October read as "closed" today. The
answer to that is somebody looking, and it is a process answer rather than a
technical one.

ACCEPT sets `reviewed_at`, which is the only thing that lets a statement
compete for a status slot. The payload keeps saying `needs_review`, so a
statement a machine read stays identifiable as one for ever.

REJECT supersedes it — the mechanism that already exists for a claim that
should stop being served — so it leaves the notices and the history too, not
merely the status slot. Nothing is deleted: `documents` still holds the page,
and re-extraction can produce the statement again if the parser improves.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime

from sqlalchemy import select

from massif.db import session_scope
from massif.ingest.fr_dates import published_date
from massif.models import Feature, Source, Statement
from massif.status import recompute_feature


def _waiting(session):
    return session.execute(
        select(Statement, Feature, Source)
        .join(Feature, Feature.id == Statement.feature_id)
        .join(Source, Source.id == Statement.source_id)
        .where(
            Statement.payload["needs_review"].as_boolean().is_(True),
            Statement.reviewed_at.is_(None),
            Statement.superseded_at.is_(None),
        )
        .order_by(Statement.observed_at.desc())
    ).all()


def _one(session, statement_id: str):
    row = session.execute(
        select(Statement, Feature, Source)
        .join(Feature, Feature.id == Statement.feature_id)
        .join(Source, Source.id == Statement.source_id)
        .where(Statement.id == statement_id)
    ).first()
    return row


def _show(statement, feature, source) -> None:
    payload = statement.payload or {}
    window = "no dates stated"
    if statement.valid_from or statement.valid_to:
        # published_date, not the raw value: Postgres returns it in the
        # server's timezone and "jusqu'au 26 septembre" printed as the 27th.
        start = f"{published_date(statement.valid_from):%d %b %Y}" if statement.valid_from else "—"
        end = f"{published_date(statement.valid_to):%d %b %Y}" if statement.valid_to else "—"
        window = f"{start} to {end}"
        if payload.get("approximate"):
            window += "  (the year is OURS, not theirs)"

    print(f"\n  id        {statement.id}")
    print(f"  feature   {feature.slug}  ({feature.name_default})")
    print(f"  source    {source.slug}")
    print(f"  says      {statement.status.value} / {statement.statement_type}")
    print(f"  window    {window}")
    print(f"  summary   {statement.summary_en}")
    if payload.get("undated_status"):
        # Rule 3 demoted it. The reviewer needs to see what it wanted to claim,
        # or "unknown" looks like the model having no opinion.
        print(f"  demoted   it wanted to say {payload['undated_status']!r}, undated")
    if payload.get("attributed_by"):
        print(f"  attributed by {payload['attributed_by']}")
    if payload.get("dates_rejected"):
        print(f"  dates      DROPPED: {payload['dates_rejected']}")
    print(f"  evidence  {(statement.original_text or '')[:300]!r}")
    if payload.get("url"):
        print(f"  page      {payload['url']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--show", metavar="ID")
    parser.add_argument("--accept", metavar="ID")
    parser.add_argument("--reject", metavar="ID")
    parser.add_argument("--note", default=None)
    args = parser.parse_args()

    with session_scope() as session:
        target = args.show or args.accept or args.reject
        if target:
            row = _one(session, target)
            if row is None:
                print(f"no statement {target}")
                return 1
            statement, feature, source = row
            _show(statement, feature, source)

            if args.show:
                return 0

            now = datetime.now(UTC)
            if args.accept:
                statement.reviewed_at = now
                statement.review_note = args.note
                verb = "accepted — it can now compete for the status slot"
            else:
                # Superseded, not deleted: the document still holds the page and
                # a better parser can produce the statement again.
                statement.superseded_at = now
                statement.review_note = args.note
                verb = "rejected — superseded, and gone from notices too"
            session.flush()
            recompute_feature(session, feature.id)
            print(f"\n  {verb}")
            print(f"  {feature.slug} recomputed")
            return 0

        rows = _waiting(session)
        if not rows:
            print("nothing waiting for review")
            return 0
        print(f"{len(rows)} statements waiting for a person\n")
        print(f"  {'id':38} {'feature':26} {'says':10} summary")
        for statement, feature, _source in rows:
            print(
                f"  {str(statement.id):38} {feature.slug[:24]:26} "
                f"{statement.status.value:10} {(statement.summary_en or '')[:46]}"
            )
        print("\n  --show ID for the evidence, then --accept ID or --reject ID")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
