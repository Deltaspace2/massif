"""Matching refuges.info entries to our huts.

The fixture is seven real entries captured from their bbox API, structured
fields only — the same subset the importer keeps, so a test cannot pass against
a shape we would never store.
"""

import json
from pathlib import Path

from massif.ingest.hut_facts import (
    Candidate,
    is_decoy,
    match_candidate,
    norm,
    read_candidate,
)

FIXTURE = Path(__file__).parent / "fixtures" / "refuges_info_bbox.json"
CANDIDATES = [
    c
    for c in (read_candidate(f) for f in json.loads(FIXTURE.read_text())["features"])
    if c is not None
]


def by_name(fragment: str) -> Candidate:
    return next(c for c in CANDIDATES if fragment in c.name)


# ------------------------------------------------------------------ reading --


def test_the_structured_fields_are_read_and_the_prose_is_not():
    cosmiques = by_name("Cosmiques")
    assert cosmiques.payload["capacity"] == 145
    assert cosmiques.payload["altitude_m"] == 3613
    assert cosmiques.payload["guarded"] is True
    assert cosmiques.payload["latrines"] is True
    assert cosmiques.payload["water"] is False
    # Their community's writing stays theirs. Copying it is exactly what their
    # robots.txt objects to, and we link to the entry instead.
    assert not {"remarque", "acces", "description"} & set(cosmiques.payload)


def test_the_phone_is_pulled_out_of_the_owner_prose_and_nothing_else_is():
    cosmiques = by_name("Cosmiques")
    assert cosmiques.payload["phone"] == "04 50 54 40 16"
    # The paragraph it came from named the wardens and linked their site.
    # Neither is structured data and neither is stored.
    assert "Gardiennes" not in json.dumps(cosmiques.payload)


def test_a_permalink_and_their_own_last_edit_are_kept():
    """Attribution is a licence condition under CC BY-SA, not a courtesy, and
    their edit date is the honest 'last confirmed' for directory data."""
    cosmiques = by_name("Cosmiques")
    assert cosmiques.url.startswith("https://www.refuges.info/point/342/")
    assert cosmiques.modified_at.startswith("2025-")


# ------------------------------------------------------------------ matching --


def test_the_old_gouter_refuge_is_refused():
    """The trap this module exists for.

    "Refuge du Goûter" matches "Ancien refuge du Goûter" at a high score AND
    inside altitude tolerance — 3817 m against 3835 m — so neither the score
    nor the physical check rejects it. The old refuge is the one the mairie's
    10 April notice is about demolishing, and hanging its capacity on the
    current hut would be plausible, silent and wrong.
    """
    decoy = Candidate(
        external_ref="9999",
        name="Ancien refuge du Goûter",
        altitude_m=3817,
        url="https://www.refuges.info/point/9999/",
        payload={"capacity": 120},
        modified_at=None,
    )
    assert is_decoy(decoy.name)
    assert match_candidate("Refuge du Goûter", 3835, [decoy]) is None


def test_decoys_are_recognised_by_word_not_substring():
    assert is_decoy("Ancienne cabane des Évettes")
    assert is_decoy("Ruines du refuge de Presset")
    # "Ancien" as a word, not as a fragment of an innocent name.
    assert not is_decoy("Refuge d'Anceau")
    assert not is_decoy("Refuge des Cosmiques")


def test_a_hut_at_the_wrong_altitude_is_a_different_building():
    twin = Candidate("1", "Refuge des Cosmiques", 2100, "u", {}, None)
    assert match_candidate("Refuge des Cosmiques", 3613, [twin]) is None


def test_a_real_match_is_found_and_scored():
    match = match_candidate("Refuge des Cosmiques", 3613, CANDIDATES)
    assert match is not None
    assert match.candidate.external_ref == "342"
    assert match.method == "fuzzy"
    assert match.score >= 88


def test_a_curated_id_beats_every_name():
    """A human decided; nothing fuzzy gets a vote after that."""
    match = match_candidate("anything at all", None, CANDIDATES, curated_ref="342")
    assert match is not None and match.method == "curated"
    assert match.candidate.name == "Refuge des Cosmiques"
    # And a curated id that is not in the response matches nothing, rather
    # than quietly falling back to guessing.
    assert match_candidate("Refuge des Cosmiques", 3613, CANDIDATES,
                           curated_ref="404404") is None


def test_no_match_is_a_normal_outcome():
    """Six of our nineteen huts are Italian and this is a French project.
    Silence is the correct answer for those, not a nearest guess."""
    assert match_candidate("Rifugio Torino", 3375, CANDIDATES) is None
    assert match_candidate("Bivacco della Fourche", 3682, CANDIDATES) is None


def test_zero_places_is_missing_data_not_a_capacity_of_zero():
    conscrits = Candidate("2", "Cabane des Conscrits", 2730, "u", {}, None)
    assert "capacity" not in conscrits.payload
    raw = {"properties": {"id": 3, "nom": "X", "coord": {"alt": 2000},
                          "type": {"valeur": "refuge gardé"},
                          "places": {"valeur": 0}}}
    assert "capacity" not in read_candidate(raw).payload


def test_norm_strips_accents_like_everything_else_here():
    assert norm("Refuge du Goûter") == "refuge du gouter"
