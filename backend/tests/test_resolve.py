"""The resolver is the load-bearing part of the pipeline. If it silently
mismatches, everything downstream is confidently wrong."""

from massif.ingest.resolve import normalise


def test_normalise_strips_accents_and_generic_nouns():
    assert normalise("Refuge du Goûter") == normalise("Refuge du Gouter")
    assert "refuge" not in normalise("Refuge du Goûter")


def test_cross_language_hut_names_collapse():
    assert normalise("Rifugio Torino") == normalise("Refuge Torino")


def test_couloir_variants_collapse():
    assert normalise("Grand Couloir du Goûter") == normalise("Grand Couloir Gouter")


def test_distinct_features_do_not_collapse():
    assert normalise("Refuge du Goûter") != normalise("Refuge des Cosmiques")
    assert normalise("Aiguille du Midi") != normalise("Aiguille du Tour")


def test_empty_input_is_safe():
    assert normalise("   ") == ""
    assert normalise("de la du") == ""
