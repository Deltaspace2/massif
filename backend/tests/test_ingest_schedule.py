"""The cron and the sources' cadences have to be compatible.

Measured 7 Sep 2026: the workflow was on an hourly cron and GitHub delivered
runs at 17:27, 19:54, 21:54, 23:25, 02:33, 07:49, 13:54 — gaps of 1.5 to 6
hours against a schedule that promised one. `ingest.yml` already warned that
"scheduled runs on Actions are queued rather than guaranteed and get dropped
under load"; what it did not anticipate is that the delivered rate is worse
than the ceiling it set.

`mbnr-live` declares a 30-minute cadence. With a 60-minute trigger it could
never be fetched inside its own rhythm even if GitHub were perfectly reliable,
so `_unchecked` — which fires at two missed intervals — flagged eight lifts
UNCHECKED permanently. A badge that is always on is a badge nobody reads, and
this one is load-bearing: it is half of the answer to "is this stale".

So: a source may not promise a cadence the trigger cannot attempt. That is the
invariant here. It does not promise GitHub will deliver — nothing can — only
that we are not asking for something structurally impossible.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "ingest.yml"
SOURCES = Path(__file__).resolve().parent.parent / "seeds" / "sources.yaml"


def cron_period_minutes(expression: str) -> int:
    """Minutes between firings, for the two shapes this workflow uses.

    Deliberately not a general cron parser: it understands `*/N * * * *` and
    `M * * * *` and raises on anything else, so a cleverer schedule has to
    come back here and teach this function rather than silently scoring zero.
    """
    minute, *rest = expression.split()
    # Every other field must be a wildcard, or the period is not what the
    # minute field says: "0 */6 * * *" fires six-hourly, and reading only the
    # first field would score it 60 and pass a check it should fail.
    if rest != ["*", "*", "*", "*"]:
        raise ValueError(f"teach this function about {expression!r}")
    # Every other field must be a wildcard, or the period is not what the
    # minute field says: "0 */6 * * *" fires six-hourly, and reading only the
    # first field would score it 60 and pass a check it should fail.
    if minute.startswith("*/"):
        return int(minute[2:])
    if minute.isdigit():
        return 60
    raise ValueError(f"teach this function about {expression!r}")


def test_no_source_asks_for_a_cadence_the_cron_cannot_attempt():
    schedule = re.search(r'cron:\s*"([^"]+)"', WORKFLOW.read_text(encoding="utf-8"))
    assert schedule, "the ingest workflow has no cron"
    period = cron_period_minutes(schedule.group(1))

    sources = yaml.safe_load(SOURCES.read_text(encoding="utf-8"))
    too_eager = [
        (s["slug"], s["fetch_interval_minutes"])
        for s in sources
        if s.get("active") and s.get("fetch_interval_minutes", 0) < period
    ]
    assert not too_eager, (
        f"the cron fires every {period} min, so these can never be fetched "
        f"inside their own cadence and will sit UNCHECKED for ever: {too_eager}"
    )


def test_the_period_reader_understands_both_shapes_and_refuses_others():
    assert cron_period_minutes("*/30 * * * *") == 30
    assert cron_period_minutes("0 * * * *") == 60
    try:
        cron_period_minutes("0 */6 * * *")
    except ValueError:
        return
    raise AssertionError("an unrecognised schedule must raise, not score zero")
