"""Point the model at ONE stored document and print what survives the guards.

    python -m massif.scripts.llm_probe                 # one silent Saint-Gervais notice
    python -m massif.scripts.llm_probe --source mairie-saint-gervais --limit 3
    python -m massif.scripts.llm_probe --all           # not just the silent ones

The same dry-run convention every scraper here has, for the one component that
did not have one: it reads a document we already store, asks the model, runs
llm.py's four guards over the answer, and prints both what was accepted and
what was thrown out. It writes NO statements. The only row it writes is the
cache entry, which is the point — run it twice and the second run is free.

Written to be the first thing you run after putting a key in .env, because
until something calls the API nothing proves the key, the package and the
response shape actually line up. It costs one call.

By default it picks documents that currently produce NOTHING, since those are
the ones the whole exercise is about: 28 of Saint-Gervais' 36 stored documents
yield no statement at all, because that parser reads titles only.
"""

from __future__ import annotations

import argparse

from sqlalchemy import select

from massif.db import session_scope
from massif.ingest.llm import read_document
from massif.ingest.llm_client import build_extractor
from massif.models import Document, Source, Statement


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="mairie-saint-gervais")
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument(
        "--all",
        action="store_true",
        help="include documents that already produce statements",
    )
    args = parser.parse_args()

    with session_scope() as session:
        extractor = build_extractor(session)
        if extractor is None:
            print(
                "No ANTHROPIC_API_KEY, so there is no extractor and nothing to "
                "probe.\n"
                "  1. put a key in .env (it is git-ignored)\n"
                "  2. pip install -e '.[llm]'\n"
                "Sources that use the model are SKIPPED without a key — this is "
                "not an error state, it is the designed one."
            )
            return 1

        source = session.scalar(select(Source).where(Source.slug == args.source))
        if source is None:
            print(f"no source {args.source!r} — check seeds/sources.yaml")
            return 1

        documents = list(
            session.scalars(
                select(Document)
                .where(Document.source_id == source.id)
                .order_by(Document.fetched_at.desc())
            )
        )
        if not args.all:
            speaks = {
                document_id
                for (document_id,) in session.execute(
                    select(Statement.document_id).where(Statement.source_id == source.id)
                )
            }
            documents = [d for d in documents if d.id not in speaks]
            print(f"{len(documents)} stored documents currently produce nothing")

        for document in documents[: args.limit]:
            text = document.raw_text or ""
            if not text.strip():
                print(f"  {document.url}: no stored text, skipped")
                continue
            print(f"\n=== {document.url}\n    {len(text):,} characters")
            raw = extractor.extract(text)
            reading = read_document(
                raw,
                text,
                document.published_at or document.fetched_at,
                model=extractor.model,
                source_url=document.url,
            )
            print(f"    model returned {len(raw)}, kept {len(reading.statements)}")
            for statement in reading.statements:
                print(f"      + {statement.status.value:10} {statement.feature_mention[:44]}")
                print(f"        {statement.summary_en}")
                print(f"        evidence: {(statement.original_text or '')[:90]!r}")
            for rejection in reading.rejected:
                print(f"      - REJECTED [{rejection.reason}] {rejection.detail[:80]}")

        hits = getattr(extractor, "hits", None)
        if hits is not None:
            print(f"\ncache: {extractor.hits} hit, {extractor.misses} paid for")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
