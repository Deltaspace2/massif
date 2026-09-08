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

REVISED 8 Sep 2026, because attempting was the wrong bar. The cron went to
`*/30` and `mbnr-live` at 30 then satisfied this check exactly — and the eight
lifts stayed badged, because what matters is what Actions DELIVERS, not what
the schedule asks for. Measured over 6-8 Sep across ten delivered scheduled
runs: min 91, median 188, mean 225, max 434 minutes. Tightening the cron from
hourly to half-hourly barely moved the median; Actions drops most firings and
asking harder does not help.

So the floor is now the measured delivery rate, not the cron period. The number
below is an observation with a date on it, and it is the kind of observation
that goes stale: if the trigger is ever moved off Actions, re-measure it and
change it here rather than assuming it improved.
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


# What GitHub Actions actually delivered, in minutes between consecutive
# successful scheduled runs, measured 6-8 Sep 2026 over ten runs:
#
#     min 91 · median 188 · mean 225 · max 434
#
# The median is the floor, rounded down to a round three hours: 188 is a
# reading off ten samples, not a constant of nature, and a floor no source can
# sit exactly on invites somebody to write 189 to get past it.
#
# The median and not the mean, which one 7-hour outlier drags up; and not the
# max, which would let a source declare a cadence so loose that OVERDUE could
# never fire at all. A badge that cannot light is as useless as one that never
# goes out.
OBSERVED_DELIVERY_MINUTES = 180


def test_no_source_asks_for_a_cadence_faster_than_we_actually_deliver():
    """The bar is delivery, not the schedule.

    A source's cadence is the yardstick `_unchecked` measures our diligence
    against, so declaring one we do not meet does not make the site fresher —
    it makes the badge permanent, and then invisible.
    """
    schedule = re.search(r'cron:\s*"([^"]+)"', WORKFLOW.read_text(encoding="utf-8"))
    assert schedule, "the ingest workflow has no cron"
    # Both bars: the cron cannot attempt faster than its period, and Actions
    # does not deliver at the period. Whichever is slower is the real floor.
    floor = max(cron_period_minutes(schedule.group(1)), OBSERVED_DELIVERY_MINUTES)

    sources = yaml.safe_load(SOURCES.read_text(encoding="utf-8"))
    too_eager = [
        (s["slug"], s["fetch_interval_minutes"])
        for s in sources
        if s.get("active") and s.get("fetch_interval_minutes", 0) < floor
    ]
    assert not too_eager, (
        f"ingest is delivered every {floor} min at best, so these can never be "
        f"read inside their own cadence and will sit OVERDUE for ever: {too_eager}"
    )


def test_the_floor_is_the_delivered_rate_and_not_merely_the_cron_period():
    """The bug this file was rewritten for.

    `*/30` plus a 30-minute source satisfied the old check exactly while eight
    lifts stayed badged. If the floor ever collapses back to the cron period,
    that returns.
    """
    schedule = re.search(r'cron:\s*"([^"]+)"', WORKFLOW.read_text(encoding="utf-8"))
    period = cron_period_minutes(schedule.group(1))
    assert OBSERVED_DELIVERY_MINUTES > period, (
        "measured delivery is no worse than the cron period — if that is really "
        "true the trigger has been fixed, so re-measure and say so here"
    )


def test_the_period_reader_understands_both_shapes_and_refuses_others():
    assert cron_period_minutes("*/30 * * * *") == 30
    assert cron_period_minutes("0 * * * *") == 60
    try:
        cron_period_minutes("0 */6 * * *")
    except ValueError:
        return
    raise AssertionError("an unrecognised schedule must raise, not score zero")
