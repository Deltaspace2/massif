"""camptocamp route conditions — and the four things they must never become.

A trip report is one person saying what they found on one day. The whole risk
in reading them is that a community rating starts driving a status badge, so
most of what follows is about what this source cannot say.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from massif.enums import StatementType, StatusValue
from massif.ingest.sources.camptocamp_outings import (
    RATINGS,
    RECENT_DAYS,
    CamptocampOutingsScraper,
    extract,
    pinned_route,
)

FIXTURES = Path(__file__).parent / "fixtures"


def envelope() -> str:
    return (FIXTURES / "camptocamp_outings_cosmiques.json").read_text(encoding="utf-8")


def envelope_with(*outings, slug="cosmiques-arete") -> str:
    return json.dumps(
        {"feature_slug": slug, "route_id": 1, "route_title": "T", "outings": list(outings)}
    )


def outing(date_start, rating, doc_id=99, title="Une sortie"):
    return {
        "document_id": doc_id,
        "date_start": date_start,
        "condition_rating": rating,
        "locales": [{"lang": "fr", "title": title}],
    }


# ------------------------------------------------------------------ what it says


def test_the_newest_rated_report_is_carried():
    found = extract(envelope(), datetime(2026, 9, 1, tzinfo=UTC))
    assert len(found) == 1
    said = found[0]
    assert said.summary_en == "Conditions reported mixed on 10 Aug 2026"
    assert said.observed_at == datetime(2026, 8, 10, tzinfo=UTC)
    assert said.feature_slug == "cosmiques-arete"


def test_every_report_links_back_to_the_entry_its_author_wrote():
    """CC BY-SA. The link back is a licence condition, per report, never one
    shared footer — the same rule the facts block is built around."""
    said = extract(envelope(), datetime(2026, 9, 1, tzinfo=UTC))[0]
    assert said.payload["permalink"].startswith("https://www.camptocamp.org/outings/")
    assert said.payload["permalink"].rstrip("/").split("/")[-1].isdigit()


# ------------------------------------------------------------ what it must not say


def test_a_condition_report_is_never_a_closure():
    """The single most important line here. "Poor" is not "shut", and a site
    that let a community rating paint a route red would be inventing closures
    out of opinions."""
    for rating in RATINGS:
        found = extract(
            envelope_with(outing("2026-08-28", rating)),
            datetime(2026, 9, 1, tzinfo=UTC),
        )
        assert found, rating
        assert found[0].status == StatusValue.UNKNOWN
        assert found[0].statement_type == StatementType.CONDITION
        assert found[0].severity == 0
        assert found[0].payload["advisory"] is True


def test_a_rating_we_do_not_recognise_says_nothing():
    """Inventing an English phrase for a value we have never seen is how a
    parser starts saying things its source did not."""
    assert (
        extract(
            envelope_with(outing("2026-08-28", "spectaculaire")),
            datetime(2026, 9, 1, tzinfo=UTC),
        )
        == []
    )


def test_an_unrated_report_says_nothing():
    """Three of the eight real reports in the fixture carry no rating at all.
    A trip happened; nobody said what they found. That is not a condition."""
    assert (
        extract(envelope_with(outing("2026-08-28", None)), datetime(2026, 9, 1, tzinfo=UTC)) == []
    )


def test_a_report_older_than_the_window_is_not_carried():
    """STALE_DAYS greys a condition at 14 days. Importing last spring's report
    would put a permanently grey line on a route page and call it coverage."""
    now = datetime(2026, 9, 1, tzinfo=UTC)
    assert extract(envelope_with(outing("2026-08-28", "good")), now)
    assert extract(envelope_with(outing("2026-04-26", "poor")), now) == []


def test_the_report_carried_is_the_newest_not_the_best():
    """Ordering by date, never by how good the news is. The fixture's newest is
    "average" while July holds two "excellent" — a source that reached past the
    recent bad report for the older good one would be flattering the mountain."""
    now = datetime(2026, 9, 1, tzinfo=UTC)
    found = extract(
        envelope_with(
            outing("2026-08-20", "excellent", doc_id=1),
            outing("2026-08-28", "poor", doc_id=2),
        ),
        now,
    )
    assert found[0].payload["condition_rating"] == "poor"
    assert found[0].payload["permalink"].endswith("/2")


# ------------------------------------------------------------------- resolution


def test_a_route_nobody_pinned_is_never_guessed_at():
    """Matching their routes by name put our Goûter route on the Kungsleden in
    Sweden, via our own alias "Voie Royale"; adding an altitude gate still left
    the Grand Couloir matched to an unrelated "Couloir Rectiligne", because
    altitude cannot separate two couloirs at the same height."""

    class Unpinned:
        external_ids = {}

    class Pinned:
        external_ids = {"camptocamp_route": 53884}

    assert pinned_route(Unpinned()) is None
    assert pinned_route(Pinned()) == 53884


def test_a_statement_is_dated_by_the_report_not_by_our_fetch():
    class StoredDocument:
        raw_text = envelope()
        raw_content = None
        published_at = None
        fetched_at = datetime(2026, 9, 1, tzinfo=UTC)

    found = CamptocampOutingsScraper().extract_stored(StoredDocument())
    assert found[0].observed_at == datetime(2026, 8, 10, tzinfo=UTC)


def test_re_extraction_judges_recency_from_the_document_not_from_today():
    """The subtle half of the re-extraction contract.

    `observed_at` comes from the report either way, so dating is safe — but the
    RECENCY WINDOW is measured against the moment passed in. Re-extracting an
    old document against today would silently drop every report that was
    current when we fetched it, and `reextract` would quietly empty a route's
    history instead of reproducing it.
    """
    old = envelope_with(outing("2026-03-02", "good"))

    class StoredInMarch:
        raw_text = old
        raw_content = None
        published_at = None
        fetched_at = datetime(2026, 3, 5, tzinfo=UTC)

    found = CamptocampOutingsScraper().extract_stored(StoredInMarch())
    assert found, "a March document must still re-extract its March report"
    assert found[0].observed_at == datetime(2026, 3, 2, tzinfo=UTC)
    # And the same envelope read as if it were today yields nothing, which is
    # what makes the assertion above about the document's clock and not luck.
    assert extract(old, datetime(2026, 9, 1, tzinfo=UTC)) == []


def test_the_window_is_the_documented_one():
    assert RECENT_DAYS == 30
