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
    assert all(status is not StatusValue.OPEN for _, status, _, _ in STATES.values()), (
        "no state may map to OPEN"
    )
    # And with words in it, an ouverture entry still emits nothing.
    assert extract(payload(entry("X", "ouverture", "Ouvert")), FETCHED) == []


def test_a_closure_becomes_a_closure():
    out = extract(payload(entry("Cabane des Rognes", "fermeture", "Fermée")), FETCHED)
    assert len(out) == 1
    assert out[0].statement_type == StatementType.CLOSURE
    assert out[0].status == StatusValue.CLOSED
    assert out[0].original_text == "Fermée"


def test_a_key_to_collect_is_a_restriction_not_a_closure():
    """ "Clés à récupérer" is a hut you can use, having arranged it. Calling
    that closed would be as wrong as calling it open."""
    out = extract(
        payload(entry("Refuge des Petoudes", "cle_a_recuperer", "Clés à récupérer")),
        FETCHED,
    )
    assert out[0].statement_type == StatementType.RESTRICTION
    assert out[0].status == StatusValue.RESTRICTED


def test_destroyed_is_flagged_for_a_human():
    """ "Détruite" says the building is gone, which is not the same claim as a
    closure and probably means the hut should not be on the map at all. That is
    a person's call: refuges.info says the Bivacco della Fourche is destroyed
    and OSM still maps it, and whichever source we read second should not get
    to settle that quietly."""
    out = extract(payload(entry("Bivouac Alberico Borgna", "detruit", "Détruite")), FETCHED)
    assert out[0].payload["needs_review"] is True
    assert out[0].severity == 3


def test_a_superseded_building_is_dropped_before_it_can_be_resolved():
    """ "Ancien refuge du Goûter — Détruite" is really in this response, and it
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
        payload(
            entry(
                "Refuge Pavillon",
                "fermeture",
                "Fermé au public",
                modified="2021-12-09 12:41:46.918419+01",
            )
        ),
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


# --------------------------------------------- the shelter type, for one value


def typed(name, kind, etat_id="ouverture", valeur="", ref=1):
    entry_ = entry(name, etat_id, valeur, ref=ref)
    entry_["properties"]["type"] = {"id": 7, "valeur": kind}
    return entry_


def test_an_unguarded_cabin_is_open_because_it_has_no_warden():
    """Seventeen of our huts are classified "cabane non gardée" and every one
    read "unknown" — which said we had failed to find something out, when the
    truth is there is nothing to find out. Nobody will ever publish an opening
    date for a building with no warden.

    CLAUDE.md draws the fact/statement line with this exact example: "The
    warden season is a statement; the bunk count is a fact."
    """
    found = extract(payload(typed("Bivouac des Périades", "cabane non gardée")), FETCHED)
    assert len(found) == 1
    assert found[0].status == StatusValue.OPEN
    assert found[0].statement_type == StatementType.OPERATIONAL_STATUS
    assert found[0].severity == 0
    assert found[0].payload["unwardened"] is True


def test_a_warden_ed_refuge_stays_unknown():
    """The whole point of reading only ONE type value. A "refuge gardé" HAS a
    season and we do not know it; saying it is open would be inventing the
    answer rather than reporting one. Same for a valley gîte d'étape."""
    assert extract(payload(typed("Refuge du Couvercle", "refuge gardé")), FETCHED) == []
    assert extract(payload(typed("Auberge du Truc", "gîte d'étape")), FETCHED) == []


def test_a_flagged_state_beats_the_type_outright():
    """A cabin they have marked shut, key-only or destroyed must not also be
    told the world it is open all year. Not resolved by severity later — the
    open claim is never emitted at all, so the two can never both stand."""
    for state, valeur in (
        ("fermeture", "Fermée"),
        ("detruit", "Détruite"),
        ("cle_a_recuperer", "Clés à récupérer"),
    ):
        found = extract(payload(typed("Cabane X", "cabane non gardée", state, valeur)), FETCHED)
        assert len(found) == 1
        assert found[0].status != StatusValue.OPEN


def test_a_destroyed_decoy_is_still_dropped_before_any_of_this():
    """The decoy guard has to run before the type is read too, or "Ancien
    refuge du Goûter" comes back as a cheerful open shelter instead of being
    dropped."""
    assert extract(payload(typed("Ancien refuge du Goûter", "cabane non gardée")), FETCHED) == []
