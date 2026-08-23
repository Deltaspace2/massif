"""Show the alias review queue: names that didn't resolve to a feature.

This is the maintenance loop that makes the whole pipeline work. Names appear
here ranked by how often they've been seen; adding the frequent ones to
features_curated.yaml aliases is the highest-leverage work on the project.
"""

from __future__ import annotations

from sqlalchemy import desc, select

from massif.db import session_scope
from massif.models import Feature, UnresolvedMention


def main() -> int:
    with session_scope() as session:
        rows = session.scalars(
            select(UnresolvedMention)
            .where(
                UnresolvedMention.resolved_to.is_(None),
                UnresolvedMention.dismissed.is_(False),
            )
            .order_by(desc(UnresolvedMention.seen_count))
            .limit(50)
        ).all()

        if not rows:
            print("review queue empty")
            return 0

        for row in rows:
            print(f"\n{row.seen_count:>4}x  {row.mention_text!r}")
            for candidate in row.candidates[:3]:
                feature = session.get(Feature, candidate["feature_id"])
                if feature:
                    print(
                        f"        ~{candidate['score']:>5}  {feature.slug}"
                        f"  (matched on {candidate['matched_on']!r})"
                    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
