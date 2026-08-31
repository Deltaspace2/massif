"""Matching refuges.info entries to our huts.

The fixture is seven real entries captured from their bbox API, structured
fields only — the same subset the importer keeps, so a test cannot pass against
a shape we would never store.
"""

import json
from pathlib import Path

from massif.ingest.hut_facts import (
    ALTITUDE_TOLERANCE_M,
    Candidate,
    is_decoy,
    match_candidate,
    match_key,
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


def test_decoys_are_recognised_in_italian_and_german_too():
    """The list was French-only, and nobody noticed because the French half
    worked.

    "Refuge Torino (ancien)" was caught, so the guard looked healthy — while
    "Rifugio Torino Vecchio" and "Bivacco Fiorio (vecchio)", both real OSM
    entries for superseded buildings, went straight through it. That only
    surfaced when the hut importer started reading OSM names rather than
    refuges.info's French ones.
    """
    assert is_decoy("Rifugio Torino Vecchio")
    assert is_decoy("Bivacco Fiorio (vecchio)")
    assert is_decoy("Vecchia capanna")
    assert is_decoy("Ruderi del rifugio")
    assert is_decoy("Alte Hütte")
    assert is_decoy("Ehemalige Berghütte")
    # The new one is "nuovo", and it is the hut that still stands.
    assert not is_decoy("Rifugio Torino Nuovo")
    # Bare "alt" is deliberately NOT a decoy word: it is a fragment of too
    # many real Alpine names to spend on a guess.
    assert not is_decoy("Refuge de l'Alt")


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
    """Silence is the correct answer when they do not have the hut.

    This test once carried the docstring "six of our nineteen huts are Italian
    and this is a French project". That was wrong, and it was wrong in the most
    expensive way — a story that explained a number, so nobody checked the
    number. refuges.info had five of those six.
    """
    assert match_candidate("Refuge des Cosmiques", 3613, []) is None
    assert match_candidate("Bivacco della Fourche", 3682, CANDIDATES) is None


# ------------------------------------------------- translating the generic --


def test_rifugio_and_refuge_are_the_same_word():
    """The bug: refuges.info is French, so our "Rifugio Torino" is their
    "Refuge Torino". Five huts lost on that one word — Gonella by 1 m of
    altitude, Vallot by 4, Torino by 7 — and were reported as absent."""
    torino = Candidate("376", "Refuge Torino (nouveau)", 3382, "u", {}, None)
    assert match_candidate("Rifugio Torino", 3375, [torino]) is not None
    assert match_key("Rifugio Torino") == match_key("Refuge Torino")


def test_translation_never_flattens_a_french_distinction():
    """The near-miss that made this a translation table rather than a synonym
    list.

    refuges.info publishes BOTH "Refuge des Conscrits" (2602 m) and "Cabane des
    Conscrits" (2730 m). They are different buildings. Folding cabane into
    refuge scored both at 100, and the wrong one won on tie-break — and we hold
    no altitude for that hut, so nothing downstream would have caught it. In
    French a cabane is unstaffed and a refuge is staffed; only words that are
    the same word in two languages may be folded.
    """
    assert match_key("Cabane des Conscrits") != match_key("Refuge des Conscrits")
    refuge = Candidate("338", "Refuge des Conscrits", 2602, "u", {}, None)
    cabane = Candidate("10483", "Cabane des Conscrits", 2730, "u", {}, None)
    # No altitude of our own for this hut — the name is the only evidence.
    match = match_candidate("Refuge des Conscrits", None, [cabane, refuge])
    assert match is not None
    assert match.candidate.external_ref == "338", "picked the wrong Conscrits hut"


def test_the_decoy_list_still_wins_after_translation():
    """Translation brings the demolished Torino within reach, so this is the
    guard that has to hold.

    "Refuge Torino (ancien)" is 3329 m against our 3375 — 46 m, comfortably
    INSIDE the 120 m tolerance, so the physical check cannot reject it. The
    decoy word list is the only thing left. The hut is pinned by external id as
    well, but this proves the fallback rather than relying on the pin.
    """
    old = Candidate("10577", "Refuge Torino (ancien)", 3329, "u", {}, None)
    assert abs(3329 - 3375) < ALTITUDE_TOLERANCE_M, "altitude alone cannot reject it"
    assert is_decoy(old.name)
    assert match_candidate("Rifugio Torino", 3375, [old]) is None


def test_zero_places_is_missing_data_not_a_capacity_of_zero():
    conscrits = Candidate("2", "Cabane des Conscrits", 2730, "u", {}, None)
    assert "capacity" not in conscrits.payload
    raw = {"properties": {"id": 3, "nom": "X", "coord": {"alt": 2000},
                          "type": {"valeur": "refuge gardé"},
                          "places": {"valeur": 0}}}
    assert "capacity" not in read_candidate(raw).payload


def test_norm_strips_accents_like_everything_else_here():
    assert norm("Refuge du Goûter") == "refuge du gouter"
