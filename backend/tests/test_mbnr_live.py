"""Parser tests built from HTML captured off the live page, not invented.

The fixtures below are verbatim m_PIOItem markup from
montblancnaturalresort.com/fr/infos-live, so a site redesign breaks these
tests rather than silently corrupting the map.
"""

from datetime import UTC, datetime

import pytest
from selectolax.parser import HTMLParser

from massif.enums import StatusValue
from massif.ingest.sources.mbnr_live import (
    extract,
    lift_counts,
    parse_counts,
    parse_item,
    sector_status,
)

# Captured live, 2026-08-24 — before the first lift of the day.
ITEM_PENDING = """
<div class="m_PIOItem"><div class="m_PIOItem_content">
<div class="m_PIOItem_timeList"><div class="m_PIOItem_time">07:20 - 16:10</div></div>
<div class="m_PIOItem_name">TPH AIGUILLE DU MIDI</div>
<div class="m_PIOItem_message"></div></div>
<div class="m_PIOItem_status"><i class="a_Icon elibertyIcon-hourglass a_IconStatusPoi a_IconStatusPoi-pending"></i></div></div>
"""

# The lift that broke the first version: two time ranges and a lunch-break note.
ITEM_LUNCH_BREAK = """
<div class="m_PIOItem"><div class="m_PIOItem_content">
<div class="m_PIOItem_timeList"><div class="m_PIOItem_time">08:30 - 13:00</div>
<div class="m_PIOItem_time">14:00 - 17:30</div></div>
<div class="m_PIOItem_name">TC VALLORCINE</div>
<div class="m_PIOItem_message">Fermé de 13h00 et 14h00</div></div>
<div class="m_PIOItem_status"><i class="a_Icon a_IconStatusPoi a_IconStatusPoi-open"></i></div></div>
"""

ITEM_TRAIL = """
<div class="m_PIOItem m_PIOItem-trail"><div class="m_PIOItem_content">
<div class="m_PIOItem_name">PISTE VERTE</div><div class="m_PIOItem_message"></div></div>
<div class="m_PIOItem_status"><i class="a_Icon a_IconStatusPoi a_IconStatusPoi-open"></i></div></div>
"""


def _item(html: str):
    return parse_item(HTMLParser(html).css_first("div.m_PIOItem"))


def test_status_read_from_icon_not_text():
    """m_PIOItem_status has no text content — the state is the icon modifier."""
    item = _item(ITEM_PENDING)
    assert item["raw_status"] == "pending"
    assert item["status"] is StatusValue.UNKNOWN


def test_name_times_and_message_are_separate_fields():
    item = _item(ITEM_LUNCH_BREAK)
    assert item["name"] == "TC VALLORCINE"
    assert item["times"] == ["08:30 - 13:00", "14:00 - 17:30"]
    assert item["message"] == "Fermé de 13h00 et 14h00"


def test_lunch_break_does_not_close_an_open_lift():
    """Regression: the first version read the 'Fermé' in the message and
    published an operating lift as closed."""
    assert _item(ITEM_LUNCH_BREAK)["status"] is StatusValue.OPEN


def test_trails_are_flagged_not_treated_as_lifts():
    assert _item(ITEM_TRAIL)["is_trail"] is True
    assert _item(ITEM_PENDING)["is_trail"] is False


def test_unknown_icon_modifier_is_recorded_not_guessed():
    html = ITEM_PENDING.replace("a_IconStatusPoi-pending", "a_IconStatusPoi-wibble")
    item = _item(html)
    assert item["raw_status"] == "wibble"
    assert item["status"] is StatusValue.UNKNOWN


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Remontées ( 0 / 4 ) Visites ( 0 / 5 ) Restaurants ( 0 / 2 )",
         {"remontées": {"open": 0, "total": 4},
          "visites": {"open": 0, "total": 5},
          "restaurants": {"open": 0, "total": 2}}),
        ("Remontées ( 0 / 3 ) Pistes ( 7 / 7 ) Restaurants ( 0 / 1 )",
         {"remontées": {"open": 0, "total": 3},
          "pistes": {"open": 7, "total": 7},
          "restaurants": {"open": 0, "total": 1}}),
    ],
)
def test_sector_counts_parsed(text, expected):
    assert parse_counts(text) == expected


def test_lift_category_picked_out_of_the_counts():
    counts = parse_counts("Remontées ( 2 / 3 ) Restaurants ( 0 / 1 )")
    assert lift_counts(counts) == {"open": 2, "total": 3}


def test_rack_railway_counts_as_uphill_transport():
    """Montenvers publishes 'Trains & Visites', not 'Remontées'."""
    counts = parse_counts("Trains & Visites ( 0 / 3 ) Restaurants ( 0 / 4 )")
    assert lift_counts(counts) == {"open": 0, "total": 3}


def test_restaurants_alone_do_not_count_as_lifts():
    assert lift_counts(parse_counts("Restaurants ( 0 / 2 )")) is None


def test_pending_sector_is_not_reported_closed():
    """Before the first lift every item is pending and every sector reads 0/N.
    Publishing that as CLOSED would declare Chamonix shut every morning."""
    items = [_item(ITEM_PENDING), _item(ITEM_PENDING)]
    status, _, note = sector_status(items, {"open": 0, "total": 2})
    assert status is StatusValue.UNKNOWN
    assert "not yet running" in note


def test_genuinely_closed_sector_reads_closed():
    closed = ITEM_PENDING.replace("a_IconStatusPoi-pending", "a_IconStatusPoi-closed")
    status, severity, note = sector_status([_item(closed)], {"open": 0, "total": 3})
    assert status is StatusValue.CLOSED
    assert severity == 1
    assert "all 3 lifts closed" in note


def test_partially_open_sector_is_restricted():
    open_item = ITEM_PENDING.replace("a_IconStatusPoi-pending", "a_IconStatusPoi-open")
    status, _, note = sector_status([_item(open_item)], {"open": 1, "total": 3})
    assert status is StatusValue.RESTRICTED
    assert "1 of 3" in note


def test_fully_open_sector_reads_open():
    open_item = ITEM_PENDING.replace("a_IconStatusPoi-pending", "a_IconStatusPoi-open")
    status, _, _ = sector_status([_item(open_item)], {"open": 3, "total": 3})
    assert status is StatusValue.OPEN


def test_extract_maps_tab_id_to_feature_slug_exactly():
    page = f"""
    <div class="o_InfoLiveTab" id="brevent">
      <div class="o_InfoLiveTab_label">Brévent - 2525 m</div>
      <div class="o_BlockOpening">
        <div class="o_BlockOpening_tabs">Remontées ( 0 / 1 ) Restaurants ( 0 / 2 )</div>
        {ITEM_PENDING}
      </div>
    </div>
    """
    statements = extract(HTMLParser(page), datetime.now(UTC))
    sector = statements[0]
    assert sector.feature_slug == "brevent"
    assert sector.extraction_confidence == 1.0
    assert sector.payload["altitude_m"] == 2525
    assert len(statements) == 2  # sector + one machine


def test_unmapped_tab_is_flagged_low_confidence_not_dropped():
    page = """
    <div class="o_InfoLiveTab" id="somewhere-new">
      <div class="o_InfoLiveTab_label">Somewhere New - 1200 m</div>
      <div class="o_BlockOpening">
        <div class="o_BlockOpening_tabs">Remontées ( 1 / 1 )</div>
      </div>
    </div>
    """
    statements = extract(HTMLParser(page), datetime.now(UTC))
    assert len(statements) == 1
    assert statements[0].feature_slug is None
    assert statements[0].extraction_confidence == 0.5


def test_machines_are_scoped_to_their_sector():
    """Regression: unscoped resolution sent TC MER DE GLACE to the Mer de
    Glace glacier and TSD INDEX to the Flégère sector, so several lifts and
    the sector aggregate competed for one status slot."""
    page = f"""
    <div class="o_InfoLiveTab" id="flegere">
      <div class="o_InfoLiveTab_label">Flégère - 1894 m</div>
      <div class="o_BlockOpening">
        <div class="o_BlockOpening_tabs">Remontées ( 0 / 2 )</div>
        {ITEM_PENDING.replace("TPH AIGUILLE DU MIDI", "TSD INDEX")}
      </div>
    </div>
    """
    statements = extract(HTMLParser(page), datetime.now(UTC))
    sector, machine = statements[0], statements[1]

    assert sector.feature_slug == "flegere"
    assert sector.parent_slug is None

    assert machine.feature_mention == "TSD INDEX"
    assert machine.parent_slug == "flegere"
    assert machine.feature_slug is None


def test_no_orphan_machines_for_unmapped_sectors():
    """An unknown sector yields its aggregate only — its lifts have no parent
    to be scoped to, so emitting them would invite exactly the mismatches
    this scoping exists to prevent."""
    page = f"""
    <div class="o_InfoLiveTab" id="brand-new-sector">
      <div class="o_InfoLiveTab_label">Brand New - 900 m</div>
      <div class="o_BlockOpening">
        <div class="o_BlockOpening_tabs">Remontées ( 0 / 1 )</div>
        {ITEM_PENDING}
      </div>
    </div>
    """
    statements = extract(HTMLParser(page), datetime.now(UTC))
    assert len(statements) == 1
    assert statements[0].feature_slug is None
