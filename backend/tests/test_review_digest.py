"""The nightly "there is something to review" notice.

The review queue only works if somebody knows it is non-empty, and the only
way to find that out was to go and look — which means it gets looked at
enthusiastically for a week and then never.

TWO THINGS THIS MUST NOT DO, both recorded at the top of `ingest.yml` from the
last time notifications went wrong here: it must not open a fresh issue every
run, because that workflow "failed forty-eight times a day and emailed every
time, which is not monitoring, it is training yourself to ignore the emails
that will matter"; and it must not count things the review page would not show,
because a number that disagrees with the page it points at is worse than no
number.

So the digest reuses `admin._waiting` rather than writing its own query. One
definition of "waiting", or the notification and the page drift apart and only
one of them has tests.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta

from massif.scripts import review_digest


class _Feature:
    def __init__(self, name: str) -> None:
        self.name_default = name
        self.slug = name.lower().replace(" ", "-")


class _Source:
    def __init__(self, slug: str) -> None:
        self.slug = slug


class _Statement:
    def __init__(self, days_old: float, status: str = "closed") -> None:
        self.observed_at = datetime.now(UTC) - timedelta(days=days_old)
        self.status = type("S", (), {"value": status})()
        self.summary_en = f"something about {status}"


def _row(name: str, source: str, days_old: float):
    return (_Statement(days_old), _Feature(name), _Source(source), None)


# ------------------------------------------------------------ the count


def test_an_empty_queue_produces_no_notice():
    """Nothing waiting is not news. A digest that fires anyway is the thing
    that teaches you to filter the address."""
    assert review_digest.digest([]) is None


def test_the_title_carries_the_count_so_the_inbox_line_is_the_message():
    """The subject is the whole notification for anyone skimming: it should be
    readable without opening anything."""
    title, _ = review_digest.digest([_row("Refuge du Requin", "hut-sites", 2)])
    assert "1" in title
    title, _ = review_digest.digest(
        [_row("Refuge du Requin", "hut-sites", 2), _row("Abri Simond", "hut-sites", 1)]
    )
    assert "2" in title


# ------------------------------------------------------------- the body


def test_the_body_names_the_features_and_where_they_came_from():
    _, body = review_digest.digest([_row("Refuge du Requin", "hut-sites", 2)])
    assert "Refuge du Requin" in body
    assert "hut-sites" in body


def test_it_says_how_old_the_oldest_is():
    """A queue of two is a chore. A queue where the oldest has been waiting a
    month means nobody is reading it, and that is a different problem with a
    different fix."""
    _, body = review_digest.digest(
        [_row("New thing", "hut-sites", 1), _row("Old thing", "hut-sites", 31)]
    )
    # The summary line specifically, not just anywhere in the body — the
    # per-item list also contains "31", so a laxer assertion passed even with
    # the oldest calculation stubbed to zero.
    assert "**31 days**" in body


def test_it_groups_by_source_so_a_noisy_one_is_obvious():
    """Forty items from one source is not forty decisions, it is one source
    emitting noise — and the useful fix is upstream, not in the panel."""
    rows = [_row(f"Hut {i}", "hut-sites", 1) for i in range(4)]
    rows.append(_row("Something", "mairie-saint-gervais", 1))
    _, body = review_digest.digest(rows)
    assert "hut-sites" in body and "mairie-saint-gervais" in body
    assert "4" in body


def test_the_body_links_to_the_panel_that_can_act_on_it():
    _, body = review_digest.digest([_row("Refuge du Requin", "hut-sites", 2)])
    assert "/admin/review" in body


# --------------------------------------------- one issue, not one per run


def test_the_body_carries_a_stable_marker_so_the_same_issue_is_reused():
    """The workflow finds the existing issue by searching for this string. A
    fresh issue every thirty minutes is the mistake `ingest.yml` already
    records: forty-eight emails a day, and then you stop reading them."""
    _, body = review_digest.digest([_row("Refuge du Requin", "hut-sites", 2)])
    assert review_digest.MARKER in body


def test_the_marker_is_not_something_a_human_would_type():
    """It is matched against issue bodies, so a phrase that could occur in a
    real report would make the digest hijack somebody's issue."""
    assert review_digest.MARKER.startswith("<!--")


# ------------------------------------- the count agrees with the page


def test_the_digest_asks_the_review_page_what_is_waiting():
    """Not a second query with the same intent. `_waiting` already excludes
    superseded statements, ones already reviewed, and features somebody has
    deactivated — three exclusions this would have had to rediscover, and the
    Bivacco della Fourche is in the third of them.
    """
    source = inspect.getsource(review_digest)
    # The import line itself, not the name: `import anything as _waiting`
    # satisfies a substring check while asking a completely different question.
    assert "from massif.admin import _waiting" in source, (
        "the digest must reuse the review page's own query, or the number in "
        "the notification and the number on the page will disagree"
    )
