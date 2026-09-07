"""What is waiting for a person, as a line and a page of markdown.

    python -m massif.scripts.review_digest        # prints, writes nothing

The review queue only works if somebody knows it is non-empty. Until now the
only way to find out was to open the panel, which means it gets read
enthusiastically for a week and then never.

ONE ISSUE, EDITED IN PLACE — never one per run. That is not a preference, it
is the mistake recorded at the top of `ingest.yml`: a workflow that "failed
forty-eight times a day and emailed every time, which is not monitoring, it is
training yourself to ignore the emails that will matter". The body carries a
`MARKER` the workflow searches for, so the same issue is found and updated.

It reuses `admin._waiting` rather than asking the same question a second way.
That query already excludes superseded statements, ones a person has already
decided, and features somebody has deactivated — the Bivacco della Fourche was
taken off the map after a rockfall and its statements went on queueing for a
verdict nobody could act on. A digest with its own query would have had to
rediscover all three, and a count that disagrees with the page it links to is
worse than no count.
"""

from __future__ import annotations

import sys
from collections import Counter
from datetime import UTC, datetime

# The admin module owns what "waiting" means. Importing it here is the point.
from massif.admin import _waiting
from massif.db import session_scope

# Hidden in the rendered issue, findable by `gh issue list --search`. Starts
# with a comment opener so it cannot collide with anything a person would
# write in a real report — the workflow matches on it, and a phrase like
# "review queue" would let the digest hijack somebody else's issue.
MARKER = "<!-- massif:review-digest -->"

PANEL = "https://api.montblancmassif.org/admin/review"


def _age_days(statement, now: datetime) -> float:
    observed = getattr(statement, "observed_at", None)
    if observed is None:
        return 0.0
    return (now - observed).total_seconds() / 86400


def digest(rows: list, now: datetime | None = None) -> tuple[str, str] | None:
    """(title, body) for the queue, or None when there is nothing waiting.

    None is the important return. Nothing waiting is not news, and a digest
    that fires anyway is exactly what teaches somebody to filter the address.
    """
    if not rows:
        return None
    now = now or datetime.now(UTC)

    by_source = Counter(src.slug for _st, _f, src, _d in rows)
    oldest = max(_age_days(st, now) for st, _f, _s, _d in rows)

    title = f"{len(rows)} statement{'' if len(rows) == 1 else 's'} waiting for review"

    lines = [
        MARKER,
        "",
        f"**{len(rows)}** waiting. Oldest has been there **{oldest:.0f} days**.",
        "",
        f"[Open the review panel]({PANEL})",
        "",
        "A model read these out of prose. None can take a status slot until a",
        "person accepts it, so the site is not currently saying any of them.",
        "",
        "### By source",
        "",
    ]
    # Grouped because forty items from one source is not forty decisions — it
    # is one source emitting noise, and the useful fix is upstream.
    for slug, count in by_source.most_common():
        lines.append(f"- **{slug}** — {count}")
    lines += ["", "### Waiting", ""]
    for statement, feature, source, _doc in rows[:25]:
        days = _age_days(statement, now)
        summary = (getattr(statement, "summary_en", "") or "")[:90]
        lines.append(
            f"- **{feature.name_default}** — {statement.status.value} · "
            f"{source.slug} · {days:.0f}d — {summary}"
        )
    if len(rows) > 25:
        # No silent caps: say what was left out rather than showing 25 and
        # letting the count above look like a mistake.
        lines.append(f"- …and {len(rows) - 25} more, in the panel.")
    return title, "\n".join(lines)


def main(argv: list[str]) -> int:
    """Print the title on the first line and the body after it.

    Two streams would be tidier, but the workflow reads this with a shell and
    one file is easier to get right than two. An empty output means nothing is
    waiting, which the workflow treats as "close the issue if it is open".
    """
    del argv
    with session_scope() as session:
        made = digest(_waiting(session))
    if made is None:
        return 0
    title, body = made
    print(title)
    print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
