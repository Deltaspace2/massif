"""refuges.info hut state — and, mostly, what it must NOT say.

The site read "unknown" on every hut because we threw this field away. The
danger in reading it is the opposite one: 108 of 122 entries carry a default
state with no words in it, and publishing those as OPEN would turn "nobody has
flagged anything" into "it is fine" — the one failure this project exists to
avoid.
"""

from datetime import UTC, datetime

from massif.enums import StatementType, StatusValue
from massif.ingest.sources.refuges_info import STATES, extract

FETCHED = datetime(2026, 9, 1, 12, tzinfo=UTC)


def entry(name, etat_id, valeur, ref=1, modified="2025-06-09 19:32:01.697977+02"):
    return {
        "properties": {
            "id": ref,
            "nom": name,
            "lien": f"https://www.refuges.info/point/{ref}/",
            "date": {"derniere_modif": modified},
            "etat": {"nom": "Etat", "id": etat_id, "valeur": valeur},
        }
    }


def payload(*entries):
    return {"features": list(entries)}


def test_an_unflagged_entry_says_nothing_at_all():
    """The guard the whole module is built around.

    id=ouverture with an empty value is the state of a wiki entry nobody has
    touched — 108 of 122 of them. It is not the community asserting the hut is
    open, and reading it that way would paint 108 huts green on no evidence.
    """
    assert extract(payload(entry("Refuge du Requin", "ouverture", "")), FETCHED) == []


def test_open_is_not_a_state_this_module_can_emit():
    """Pinned directly, because the empty-value guard hid it.

    Mutation testing added "ouverture" to the state map and every test still
    passed — the fixtures all had an empty value, so the other guard caught
    them by luck. If an entry ever carries id=ouverture WITH words in it, that
    mapping would publish a hut as OPEN on the strength of a wiki default.
    This source can say a hut is shut, restricted or gone. It can never say a
    hut is open, because it does not know.
    """
    assert "ouverture" not in STATES
    assert all(
        status is not StatusValue.OPEN for _, status, _, _ in STATES.values()
    ), "no state may map to OPEN"
    # And with words in it, an ouverture entry still emits nothing.
    assert extract(payload(entry("X", "ouverture", "Ouvert")), FETCHED) == []


def test_a_closure_becomes_a_closure():
    out = extract(payload(entry("Cabane des Rognes", "fermeture", "Fermée")), FETCHED)
    assert len(out) == 1
    assert out[0].statement_type == StatementType.CLOSURE
    assert out[0].status == StatusValue.CLOSED
    assert out[0].original_text == "Fermée"


def test_a_key_to_collect_is_a_restriction_not_a_closure():
    """"Clés à récupérer" is a hut you can use, having arranged it. Calling
    that closed would be as wrong as calling it open."""
    out = extract(
        payload(entry("Refuge des Petoudes", "cle_a_recuperer", "Clés à récupérer")),
        FETCHED,
    )
    assert out[0].statement_type == StatementType.RESTRICTION
    assert out[0].status == StatusValue.RESTRICTED


def test_destroyed_is_flagged_for_a_human():
    """"Détruite" says the building is gone, which is not the same claim as a
    closure and probably means the hut should not be on the map at all. That is
    a person's call: refuges.info says the Bivacco della Fourche is destroyed
    and OSM still maps it, and whichever source we read second should not get
    to settle that quietly."""
    out = extract(payload(entry("Bivouac Alberico Borgna", "detruit", "Détruite")), FETCHED)
    assert out[0].payload["needs_review"] is True
    assert out[0].severity == 3


def test_a_superseded_building_is_dropped_before_it_can_be_resolved():
    """"Ancien refuge du Goûter — Détruite" is really in this response, and it
    scores well above the resolver's 88 floor against our live Refuge du
    Goûter. The resolver has no decoy list; that guard lives in the hut
    matcher. Without this, a destroyed-building notice lands on the working
    hut 20 m away and closes it."""
    out = extract(payload(entry("Ancien refuge du Goûter", "detruit", "Détruite")), FETCHED)
    assert out == []


def test_the_date_is_theirs_not_ours():
    """A state last edited in 2021 is a 2021 observation. Dating it now() would
    let a four-year-old wiki edit outrank this morning's arrêté on recency, and
    would hide its age from the staleness rules."""
    out = extract(
        payload(entry("Refuge Pavillon", "fermeture", "Fermé au public",
                      modified="2021-12-09 12:41:46.918419+01")),
        FETCHED,
    )
    assert out[0].observed_at.year == 2021
    assert out[0].observed_at != FETCHED


def test_an_undateable_entry_falls_back_to_the_fetch_not_to_silence():
    out = extract(payload(entry("X", "fermeture", "Fermé", modified="not a date")), FETCHED)
    assert out[0].observed_at == FETCHED


def test_an_unknown_state_id_is_not_guessed_at():
    """A new id we have never seen emits nothing rather than being mapped to
    the nearest thing we recognise."""
    assert extract(payload(entry("X", "some_new_state", "Quelque chose")), FETCHED) == []


def test_a_state_with_an_id_but_no_words_is_still_a_default():
    assert extract(payload(entry("X", "fermeture", "   ")), FETCHED) == []


def test_the_permalink_travels_with_the_statement():
    """CC BY-SA: the link back is a licence condition, not a courtesy."""
    out = extract(payload(entry("Cabane des Rognes", "fermeture", "Fermée", ref=42)), FETCHED)
    assert out[0].payload["permalink"].endswith("/point/42/")
    assert out[0].payload["refuges_info_id"] == "42"
