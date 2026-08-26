"""Re-run extraction over stored documents. No network.

    python -m massif.scripts.reextract mairie-saint-gervais
    python -m massif.scripts.reextract mairie-saint-gervais --dry-run

`documents` is immutable and never deleted precisely so that improving a
parser means re-running it over history rather than re-fetching. Until now
there was no way in: `collect()` skips documents whose content hash is
unchanged, so a better classifier could not be applied to anything already
stored. Migration 0002 paid for that gap by deleting documents purely to
defeat the hash check and force a refetch, and said so at the time.

Grain is the document. Extraction is a function of one document, so one
document's whole prior output is retired and replaced by its whole new
output. That avoids pairing old statements to new ones — a mapping that does
not exist, because an improved parser can emit fewer statements than it did
before, or none at all. Retiring by `document_id` makes the shrink-to-zero
case fall out correctly instead of leaving orphans that keep voting.

Nothing is deleted. Superseded statements stay readable as a record of what
the parser used to think.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from massif.db import session_scope
from massif.ingest.registry import SCRAPERS
from massif.ingest.resolve import FeatureResolver
from massif.models import Document, Source, Statement
from massif.status import recompute_many


def _feature_key(value) -> uuid.UUID:
    """Resolution returns feature ids as str, ORM rows give UUID. Both land in
    the same `touched` set, so normalise or every feature is recomputed twice
    and the reported count is double the truth."""
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="reextract")
    parser.add_argument("slug", help="source slug, e.g. mairie-saint-gervais")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would change and roll back",
    )
    args = parser.parse_args(argv[1:])

    scraper_cls = SCRAPERS.get(args.slug)
    if scraper_cls is None:
        print(f"no scraper registered for {args.slug!r}", file=sys.stderr)
        return 1
    scraper = scraper_cls()

    now = datetime.now(UTC)
    retired = created = failed = unresolved = 0
    touched: set = set()

    with session_scope() as session:
        source = session.scalar(select(Source).where(Source.slug == args.slug))
        if source is None:
            print(f"source {args.slug!r} not seeded", file=sys.stderr)
            return 1

        documents = list(
            session.scalars(
                select(Document)
                .where(Document.source_id == source.id)
                .order_by(Document.fetched_at)
            )
        )
        if not documents:
            print(f"{args.slug}: no stored documents")
            return 0

        resolver = FeatureResolver(session)

        for document in documents:
            try:
                extracted = scraper.extract_stored(document)
            except NotImplementedError as exc:
                print(f"{exc}", file=sys.stderr)
                return 1
            except Exception as exc:
                # One malformed page must not block re-extraction of the rest.
                # Recorded on the document rather than only printed, so a
                # failure is visible later without re-reading the console.
                failed += 1
                document.extraction_error = f"{type(exc).__name__}: {exc}"
                print(
                    f"  {document.url} failed: {type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )
                continue

            old = list(
                session.scalars(
                    select(Statement).where(
                        Statement.document_id == document.id,
                        Statement.superseded_at.is_(None),
                    )
                )
            )
            # Nothing before, nothing now — no write, no noise.
            if not old and not extracted:
                continue

            for statement in old:
                statement.superseded_at = now
                touched.add(_feature_key(statement.feature_id))
                retired += 1

            for item in extracted:
                statement = scraper.resolve_and_build(
                    session, source, document, item, resolver
                )
                if statement is None:
                    unresolved += 1
                    continue
                session.add(statement)
                touched.add(_feature_key(statement.feature_id))
                created += 1

            document.extracted_at = now
            document.extraction_error = None

        session.flush()
        recompute_many(session, touched)

        verb = "would retire" if args.dry_run else "retired"
        print(
            f"{args.slug}: {len(documents)} documents, {verb} {retired} "
            f"statements, wrote {created}, {len(touched)} features recomputed"
        )
        if unresolved:
            print(
                f"  {unresolved} mentions did not resolve — "
                f"run massif.scripts.review_queue"
            )
        if failed:
            print(f"  {failed} documents failed to extract", file=sys.stderr)

        if args.dry_run:
            session.rollback()
            print("  dry run — rolled back")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
