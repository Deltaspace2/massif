"""Rebuild feature_status for every feature, from scratch.

feature_status is a cache. Ingest updates only what it touched, which is right
for a 30-minute cron and wrong after anything that edits statements out of
band — a migration, a manual correction, a changed resolution rule. Run this
whenever statements were altered by something other than a scrape.

    python -m massif.scripts.recompute
"""

from __future__ import annotations

from sqlalchemy import delete, select

from massif.db import session_scope
from massif.models import FeatureStatus, Statement
from massif.status import recompute_feature


def main() -> int:
    with session_scope() as session:
        # A status with no statement behind it is unsourced: nothing to show,
        # nothing to link to. Drop before rebuilding.
        orphans = session.execute(
            delete(FeatureStatus).where(FeatureStatus.statement_id.is_(None))
        ).rowcount
        if orphans:
            print(f"dropped {orphans} orphaned status rows")

        feature_ids = list(session.scalars(select(Statement.feature_id).distinct()))
        for feature_id in feature_ids:
            recompute_feature(session, feature_id)

        print(f"recomputed {len(feature_ids)} features with statements")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
