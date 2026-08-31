"""Rendering directory facts, and refusing to render them unattributed.

refuges.info is CC BY-SA 2.0. Attribution is a licence condition, not a
courtesy, so the interesting cases here are the refusals: every path that would
put someone's community's work on the page without a credit must produce
nothing at all. A missing block is visible. A missing credit is not.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import yaml

from massif.main import _fact_block

SOURCES = Path(__file__).parents[1] / "seeds" / "sources.yaml"


@dataclass
class FakeFact:
    """Only the attributes _fact_block reads. A real FeatureFact needs a
    database; this function does not."""

    payload: dict = field(default_factory=dict)
    source_url: str = "https://www.refuges.info/point/335/refuge-du-Gouter/"
    source_modified_at: datetime | None = datetime(2026, 6, 30, tzinfo=UTC)
    fetched_at: datetime | None = datetime(2026, 8, 31, tzinfo=UTC)


@dataclass
class FakeSource:
    name: str = "Refuges.info"
    url: str = "https://www.refuges.info/"
    source_type: str = "community"
    fetch_config: dict = field(
        default_factory=lambda: {
            "licence": "CC BY-SA 2.0",
            "licence_url": "https://creativecommons.org/licenses/by-sa/2.0/",
        }
    )


FULL = {"capacity": 120, "guarded": True, "water": False, "altitude_m": 3815}


# ------------------------------------------------------------ attribution --


def test_a_source_with_no_licence_renders_nothing():
    """The guard the whole file exists for.

    The licence lives in seeds/sources.yaml, so a future facts source can be
    added without one. If that produced a block anyway, we would publish a
    community's work uncredited — and the page would look completely normal.
    """
    source = FakeSource(fetch_config={"notes": "some other directory"})
    assert _fact_block(FakeFact(payload=FULL), source) is None


def test_the_seed_actually_carries_the_licence_refuges_info_needs():
    """The other half of the guard, on the producer side.

    _fact_block refusing without a licence fails safe, but it fails INVISIBLY:
    drop the two lines from the seed and every facts block on the site quietly
    disappears with the whole suite still green. This pins the data, which is
    the half most likely to be edited by someone who does not know it is
    load-bearing.
    """
    entry = next(
        row
        for row in yaml.safe_load(SOURCES.read_text(encoding="utf-8"))
        if row["slug"] == "refuges-info"
    )
    assert entry["licence"] == "CC BY-SA 2.0"
    assert entry["licence_url"].startswith("https://creativecommons.org/")


def test_a_row_with_no_permalink_renders_nothing():
    """CC BY-SA wants a link back to the entry, not just the site name.
    source_url is NOT NULL in the schema; this pins the behaviour anyway,
    because the column being non-null is not the same as it being non-empty."""
    assert _fact_block(FakeFact(payload=FULL, source_url=""), FakeSource()) is None


def test_the_credit_carries_the_entry_not_just_the_site():
    block = _fact_block(FakeFact(payload=FULL), FakeSource())
    assert block is not None
    assert block["permalink"].endswith("/point/335/refuge-du-Gouter/")
    assert block["licence"] == "CC BY-SA 2.0"
    assert block["licence_url"].startswith("https://creativecommons.org/")
    # The site itself, kept separately — naming the project is not the same as
    # linking the entry, and the licence asks for the latter.
    assert block["source"]["url"] == "https://www.refuges.info/"


# ----------------------------------------------------------------- values --


def test_false_survives_and_absent_stays_absent():
    """The three-state rule.

    `water: false` is a fact — the Charpoua has no water. A missing `latrines`
    key is refuges.info declining to say. Dropping falsey values would turn the
    first into the second and invent an answer to a question nobody asked.
    """
    block = _fact_block(FakeFact(payload={"water": False, "capacity": 14}), FakeSource())
    assert block is not None
    assert block["values"]["water"] is False
    assert "latrines" not in block["values"]


def test_the_prose_and_the_type_label_are_not_published():
    """Structured fields only. `coord_precision` is their French sentence about
    how they mapped the point, and `kind` is a French type label whose one
    useful bit is already read out into `guarded`. Neither belongs on an
    English page that promises to say things in English."""
    block = _fact_block(
        FakeFact(
            payload={
                "capacity": 40,
                "kind": "refuge gardé",
                "coord_precision": "Coordonnées pointées sur photos aériennes",
                "name_local": "Refuge du Requin",
            }
        ),
        FakeSource(),
    )
    assert block is not None
    assert set(block["values"]) == {"capacity"}


def test_an_entry_with_no_facts_left_renders_nothing():
    """A matched hut whose entry carries only prose would otherwise produce a
    heading, a credit, and an empty table."""
    assert _fact_block(FakeFact(payload={"coord_precision": "..."}), FakeSource()) is None


# ----------------------------------------------------------------- clocks --


def test_their_edit_date_and_our_fetch_stay_separate():
    """Rule 10, on a source where the gap is enormous: entries are routinely
    edited years before we pull them, and collapsing the two columns would
    either age a perfectly good bunk count into a warning or claim we checked
    something in 2024."""
    block = _fact_block(FakeFact(payload=FULL), FakeSource())
    assert block is not None
    assert block["source_modified_at"].year == 2026
    assert block["fetched_at"] != block["source_modified_at"]
    # Facts do not carry a verdict about now.
    assert "stale" not in block
    assert "status" not in block
