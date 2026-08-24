"""Status classification is where a scraper silently lies. 'non ouvert'
containing 'ouvert' is exactly the bug that would show a closed lift as open."""

import pytest

from massif.enums import StatusValue
from massif.ingest.sources.mbnr_live import classify, parse_hours


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Aiguille du Midi — Ouvert", StatusValue.OPEN),
        ("Grands Montets : Fermé", StatusValue.CLOSED),
        ("Télésiège des Bossons - fermeture saisonniere", StatusValue.CLOSED),
        ("Brévent non ouvert", StatusValue.CLOSED),
        ("Montenvers en service 08:30 - 16:30", StatusValue.OPEN),
        ("Flégère hors service", StatusValue.CLOSED),
    ],
)
def test_status_classification(text, expected):
    verdict = classify(text)
    assert verdict is not None
    assert verdict[0] is expected


def test_negation_beats_substring():
    """The trap: 'non ouvert' must not match 'ouvert' first."""
    assert classify("non ouvert")[0] is StatusValue.CLOSED


def test_no_status_word_returns_none():
    assert classify("Aiguille du Midi 3842 m") is None


def test_hours_parsed():
    assert parse_hours("Ouvert 07:20 - 16:10") == {
        "first_lift": "07:20",
        "last_lift": "16:10",
    }
    assert parse_hours("Ouvert 8h30 - 16h30") == {
        "first_lift": "08:30",
        "last_lift": "16:30",
    }


def test_hours_absent_is_empty_not_wrong():
    assert parse_hours("Fermé") == {}
