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


def test_the_elided_french_article_is_not_left_in_the_key():
    """`d'` and `l'` lose their apostrophe when punctuation is stripped, and
    the orphaned letter stays in the key as its own token.

    That is enough similarity to matter: "REFUGE D'ARGENTIÈRE" normalised to
    "d argentiere" and scored 86 against our own hut's alias "Argentière hut"
    — under the 88 floor — so FFCAM's season for it went to the review queue
    instead of onto the hut. Same family as rule 1: French normalised almost
    right matches nothing, and does it quietly.
    """
    assert normalise("REFUGE D'ARGENTIÈRE") == "argentiere"
    assert normalise("Cabane d'Orny") == "orny"
    assert normalise("L'Index") == "index"
    # A real word that merely starts with those letters is untouched.
    assert normalise("Dent du Géant") == "dent geant"
    assert normalise("Refuge du Lac Blanc") == "lac blanc"
