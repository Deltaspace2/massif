"""Calendar parser tests. Fixtures mirror the RSC payload shape captured live."""

import json
from datetime import UTC, datetime

from massif.enums import StatementType, StatusValue
from massif.ingest.sources.mbnr_openings import (
    as_datetime,
    clean_title,
    extract,
    find_objects,
    flight_payload,
    resolve_slug,
    walk_rows,
)


def _page(block: dict) -> str:
    """Wrap a block the way Next.js actually ships it: a JSON string inside a
    push(). Compact separators matter — the real payload is `{"a":"b"}` with
    no spaces, and the first version of this fixture used json.dumps defaults,
    so the marker never matched and every extract test saw an empty page."""
    inner = json.dumps(json.dumps(block, separators=(",", ":")))
    return f"<script>self.__next_f.push([1,{inner}])</script>"


SUMMER = {
    "_modelApiKey": "block_table",
    "seasonType": "summer",
    "table": [
        {
            "hide": False,
            "startDate": "2026-05-01",
            "endDate": "2026-11-01",
            "list": [
                {
                    "columnTitleOne": " Ouverture*",
                    "table": [
                        {
                            "__typename": "TableLineDateRecord",
                            "title": "Aiguille du Midi",
                            "subtitle": "Chamonix Mont-Blanc - 3842 m",
                            "valueOne": "2026-05-01",
                            "valueTow": "2026-11-01",
                        },
                        {
                            "__typename": "TableLineDateRecord",
                            "title": "Balme",
                            "subtitle": "Le Tour - 2270 m",
                            "valueOne": "2026-06-20",
                            "valueTow": "2026-09-20",
                        },
                        {
                            "__typename": "TableLineDateRecord",
                            "title": "Balme",
                            "subtitle": "Vallorcine - 2270 m",
                            "valueOne": "2026-07-04",
                            "valueTow": "2026-09-13",
                        },
                    ],
                }
            ],
        }
    ],
}


def test_flight_payload_survives_escaped_quotes():
    """The chunks are JSON string literals full of escapes — a regex that
    handles them correctly is a regex nobody should have to read.

    The payload is JSON *text*, so quotes inside a string value stay escaped.
    The property that matters is that it parses back to the original object.
    """
    html = _page({"_modelApiKey": "block_table", "note": 'has "quotes" inside'})
    assert json.loads(flight_payload(html))["note"] == 'has "quotes" inside'


def test_rows_found_regardless_of_nesting_depth():
    """Recursive, so a CMS reshuffle yields fewer rows or zero — never wrong
    ones."""
    deep = {"a": {"b": [{"c": {"__typename": "TableLineDateRecord", "title": "X"}}]}}
    assert [r["title"] for r in walk_rows(deep)] == ["X"]


def test_find_objects_returns_the_enclosing_block():
    payload = flight_payload(_page(SUMMER))
    blocks = list(find_objects(payload, '"_modelApiKey":"block_table"'))
    assert blocks and blocks[0]["seasonType"] == "summer"


def test_iso_dates_parsed_and_end_of_day_inclusive():
    assert as_datetime("2026-05-01") == datetime(2026, 5, 1, 0, 0, tzinfo=UTC)
    end = as_datetime("2026-11-01", end_of_day=True)
    assert end is not None and end.hour == 23
    assert as_datetime(None) is None
    assert as_datetime("01/05/2026") is None  # localised dates are never trusted


def test_asterisk_flagged_not_silently_stripped():
    assert clean_title("Montenvers - Mer de Glace*") == ("Montenvers - Mer de Glace", True)
    assert clean_title("Brévent") == ("Brévent", False)


def test_balme_sides_resolve_to_different_features():
    """The operator runs Le Tour and Vallorcine on different summer seasons
    under one row title. Both landing on the sector would leave two schedules
    competing for one status slot all summer."""
    assert resolve_slug("Balme", "Le Tour - 2270 m") == "balme-le-tour"
    assert resolve_slug("Balme", "Vallorcine - 2270 m") == "balme-le-tour-tc-vallorcine"
    # Regression: substring matching filed the whole winter domain against
    # the Vallorcine gondola, because "vallorcine" appears inside this.
    assert resolve_slug("Balme", "Le Tour - Vallorcine - 2270 m") == "balme-le-tour"
    assert resolve_slug("Balme", "Le Tour - Vallorcine") == "balme-le-tour"


def test_extract_end_to_end():
    statements = extract(_page(SUMMER), datetime.now(UTC))
    assert len(statements) == 3

    by_slug = {s.feature_slug: s for s in statements}
    assert "balme-le-tour" in by_slug
    assert "balme-le-tour-tc-vallorcine" in by_slug

    midi = by_slug["aiguille-du-midi"]
    assert midi.statement_type is StatementType.OPENING
    # A schedule says what is planned, never what is true now.
    assert midi.status is StatusValue.UNKNOWN
    assert midi.valid_from == datetime(2026, 5, 1, 0, 0, tzinfo=UTC)
    assert midi.payload["season"] == "summer"
    assert midi.payload["altitude_m"] == 3842
    assert "indicative" in midi.summary_en


def test_duplicate_rows_deduped_on_title_and_subtitle():
    doubled = json.loads(json.dumps(SUMMER))
    rows = doubled["table"][0]["list"][0]["table"]
    rows.extend(json.loads(json.dumps(rows)))
    assert len(extract(_page(doubled), datetime.now(UTC))) == 3


def test_text_rows_without_dates_are_skipped():
    block = json.loads(json.dumps(SUMMER))
    block["table"][0]["list"][0]["table"] = [
        {"__typename": "TableLineDateRecord", "title": "Note", "subtitle": ""}
    ]
    assert extract(_page(block), datetime.now(UTC)) == []


def test_object_at_index_zero_is_found():
    """Regression: find_objects looped `while start > 0`, so an object
    beginning at index 0 was skipped entirely. Never visible against the live
    page, where the block sits deep inside a 200 KB payload."""
    text = '{"_modelApiKey":"block_table","seasonType":"summer"}'
    blocks = list(find_objects(text, '"_modelApiKey":"block_table"'))
    assert len(blocks) == 1
    assert blocks[0]["seasonType"] == "summer"


def test_nested_object_still_found():
    text = '{"outer":[{"_modelApiKey":"block_table","seasonType":"winter"}]}'
    blocks = list(find_objects(text, '"_modelApiKey":"block_table"'))
    assert blocks and blocks[0]["seasonType"] == "winter"


def test_one_row_can_cover_two_sectors():
    """The calendar publishes a single "Megève" row, subtitle "Evasion
    Mont-Blanc" — the linked domain. Mapping it to Rochebrune alone left
    Mont d'Arbois with no season, and on a map that colours by season that
    read as "no idea" when the operator had in fact published one."""
    from massif.ingest.sources.mbnr_openings import resolve_slugs

    assert resolve_slugs("Megève", "Evasion Mont-Blanc -2350 m") == [
        "megeve-rochebrune",
        "megeve-mont-arbois",
    ]


def test_single_target_rows_are_unaffected():
    from massif.ingest.sources.mbnr_openings import resolve_slugs

    assert resolve_slugs("Aiguille du Midi", "Chamonix - 3842 m") == ["aiguille-du-midi"]
    assert resolve_slugs("Balme", "Vallorcine - 2270 m") == ["balme-le-tour-tc-vallorcine"]


def test_unknown_row_yields_nothing_to_map():
    from massif.ingest.sources.mbnr_openings import resolve_slugs

    assert resolve_slugs("Somewhere New", "") == []


def test_megeve_row_emits_a_statement_per_sector():
    block = json.loads(json.dumps(SUMMER))
    block["table"][0]["list"][0]["table"] = [
        {
            "__typename": "TableLineDateRecord",
            "title": "Megève",
            "subtitle": "Evasion Mont-Blanc -2350 m",
            "valueOne": "2026-06-20",
            "valueTow": "2026-09-06",
        }
    ]
    statements = extract(_page(block), datetime.now(UTC))
    assert {s.feature_slug for s in statements} == {
        "megeve-rochebrune",
        "megeve-mont-arbois",
    }


def test_multi_target_keys_are_accent_free():
    """Guard rail. MULTI_TARGETS is looked up on accent-stripped text, so an
    accented key silently never matches — which is how "Megève" missed
    "megeve" and Mont d'Arbois lost its season. Four separate bugs in this
    project have been an accent; this one stays caught."""
    from massif.ingest.fr_dates import strip_accents
    from massif.ingest.sources.mbnr_openings import MULTI_TARGETS

    for key in MULTI_TARGETS:
        assert key == strip_accents(key).lower(), (
            f"{key!r} will never match: keys must be accent-free and lowercase"
        )
