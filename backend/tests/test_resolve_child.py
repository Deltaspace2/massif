from massif.ingest.base import slugify


def test_slugify_strips_accents_and_punctuation():
    assert slugify("TC MONT D ARBOIS") == "tc-mont-d-arbois"
    assert slugify("Télésiège des Bossons") == "telesiege-des-bossons"
    assert slugify("FUNI 2000") == "funi-2000"


def test_slugify_collapses_separators():
    assert slugify("TPH  --  BREVENT") == "tph-brevent"
    assert slugify("  spaced  ") == "spaced"
