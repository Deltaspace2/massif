"""Matching refuges.info entries to our huts, and reading their fields.

refuges.info is a French community wiki for mountain shelters — capacity,
altitude, warden, water — published under CC BY-SA 2.0 with a read-only bbox
API. Its robots.txt is a long complaint about bots eating resources a volunteer
pays for, and it is a fair complaint, so: one request a week for the whole
massif, structured fields only, never the prose, and a link back on every hut.
Their community's writing stays theirs.

Everything here is pure. The fetching lives in scripts/import_hut_facts.py so
that the part that can be wrong is the part that can be tested.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from rapidfuzz import fuzz

# A hut is a building. If the name matches but the altitude is 300 m out, it is
# a different building — the same argument that stopped the route importer
# drawing the Goûter route up a mountain 20 km north.
ALTITUDE_TOLERANCE_M = 120

# Above this, a name match is trusted; below it, the entry goes unmatched
# rather than being guessed at.
FUZZY_FLOOR = 88.0

# Names that look like ours and are not. This list exists because
# "Refuge du Goûter" matches "Ancien refuge du Goûter" at a high score AND
# within altitude tolerance — 3817 m against 3835 m — so neither the score nor
# the physical check catches it. The old Goûter refuge is the one the mairie's
# 10 April notice is about DEMOLISHING. Hanging its capacity on the current
# hut would be this project's signature failure: plausible, silent, wrong.
DECOYS = re.compile(r"\b(ancien|ancienne|ruine|ruines|ex|vestiges?|projet)\b")

# Their type vocabulary, reduced to the one thing we render.
GUARDED = {"refuge gardé": True, "gîte d'étape": True, "refuge non gardé": False,
           "cabane non gardée": False, "abri": False, "bivouac": False}


# refuges.info is a French site, so it writes Italian huts with the French
# generic: our "Rifugio Torino" is their "Refuge Torino". The generic word
# carries no identifying information — what tells two huts apart is always the
# part after it — so it is folded to a single token before scoring. This was
# worth exactly five huts. All five scored 85.5 or 82.8 against a floor of 88,
# and lost on that one word while their altitudes sat 1, 4 and 7 m from ours:
# Gonella, Torino, Monzino, Elisabetta and Vallot were all reported as "no
# entry", and the importer said the Italian side was not covered. It is.
# TRANSLATION ONLY — Italian to French. Never type-flattening. The first
# version of this folded abri, cabane and gite into refuge as well, and
# immediately attached "Cabane des Conscrits" (2730 m) to our Refuge des
# Conscrits (2602 m): two different buildings, both scoring 100, the wrong one
# winning on tie-break, and no altitude recorded for that hut to catch it. In
# French those words are a real distinction — a cabane is unstaffed, a refuge
# is staffed — and collapsing them invents matches. Each pair below is the
# same word in two languages.
GENERIC_FORMS = {
    "rifugio": "refuge", "refugio": "refuge",
    "bivacco": "bivouac", "biwak": "bivouac",
    "capanna": "cabane",
    "riparo": "abri",
}


def match_key(text: str) -> str:
    """`norm`, with the hut-type word folded so French and Italian compare equal.

    Deliberately NOT used by `is_decoy`, and not by anything that has to read a
    name as written. Fold the generic there and "Refuge Torino (ancien)" stops
    being recognisable as the old refuge it is — which is the one mistake this
    module exists to prevent.
    """
    return " ".join(GENERIC_FORMS.get(word, word) for word in norm(text).split())


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-z0-9\s]", " ", text.casefold())
    return re.sub(r"\s+", " ", text).strip()


@dataclass
class Candidate:
    external_ref: str
    name: str
    altitude_m: int | None
    url: str
    payload: dict
    modified_at: str | None


@dataclass
class Match:
    candidate: Candidate
    score: float
    method: str


def is_decoy(name: str) -> bool:
    """Does the name say this is the old one, the ruin, or the plan?"""
    return bool(DECOYS.search(norm(name)))


def read_candidate(feature: dict) -> Candidate | None:
    """One GeoJSON feature from their bbox API, reduced to what we keep.

    Deliberately not: `remarque`, `acces`, `description`. Those are their
    community's writing, in French, carrying wiki markup, and copying them is
    precisely what their robots.txt objects to. We link instead.
    """
    props = feature.get("properties") or {}
    ref = props.get("id")
    name = (props.get("nom") or "").strip()
    if ref is None or not name:
        return None

    coord = props.get("coord") or {}
    info = props.get("info_comp") or {}

    def flag(key: str) -> bool | None:
        entry = info.get(key)
        if not isinstance(entry, dict):
            return None
        value = (entry.get("valeur") or "").strip().lower()
        return {"oui": True, "non": False}.get(value)

    type_label = ((props.get("type") or {}).get("valeur") or "").strip()
    places = (props.get("places") or {}).get("valeur")

    payload = {
        "name_local": name,
        "kind": type_label or None,
        "guarded": GUARDED.get(type_label.lower()),
        # 0 places on a guarded refuge means "they have not filled it in",
        # not "it sleeps nobody". Storing the zero would render as a fact.
        "capacity": places if isinstance(places, int) and places > 0 else None,
        "water": flag("eau"),
        "latrines": flag("latrines"),
        "altitude_m": coord.get("alt"),
        # How THEY say the coordinates were derived. Kept because this project
        # already refuses to imply precision it does not have, and they are
        # unusually honest about it.
        "coord_precision": ((coord.get("precision") or {}).get("nom")),
        "phone": _phone(props),
    }
    return Candidate(
        external_ref=str(ref),
        name=name,
        altitude_m=coord.get("alt"),
        url=props.get("lien") or "",
        payload={k: v for k, v in payload.items() if v is not None},
        modified_at=((props.get("date") or {}).get("derniere_modif")),
    )


_PHONE = re.compile(r"(?:\+33|0)\s?\d(?:[\s.\-]?\d{2}){4}")


def _phone(props: dict) -> str | None:
    """The owner field is free prose with a phone number buried in it.

    Extracting one number is a regex; anything more would be reading their
    paragraph and calling it structured data.
    """
    text = ((props.get("proprio") or {}).get("valeur")) or ""
    found = _PHONE.search(text)
    return re.sub(r"[\s.\-]+", " ", found.group(0)).strip() if found else None


def match_candidate(
    our_name: str,
    our_altitude_m: int | None,
    candidates: list[Candidate],
    *,
    curated_ref: str | None = None,
) -> Match | None:
    """Pick their entry for one of our huts, or nothing.

    Order: a curated external id always wins, because a human decided it. Then
    name similarity, floored, with decoys removed and altitude checked.

    Returning None is still a perfectly good outcome, but it used to be claimed
    far too readily: this reported six huts as absent when refuges.info had
    five of them, under the French generic. Only Bivacco della Fourche is
    genuinely not there.
    """
    if curated_ref:
        for candidate in candidates:
            if candidate.external_ref == str(curated_ref):
                return Match(candidate, 100.0, "curated")
        return None

    ours = match_key(our_name)
    best: Match | None = None
    for candidate in candidates:
        # Read as written, never through match_key: the decoy list is the only
        # thing separating our Torino from the demolished one 46 m below it,
        # which is well inside the altitude tolerance.
        if is_decoy(candidate.name):
            continue
        score = fuzz.WRatio(ours, match_key(candidate.name))
        if score < FUZZY_FLOOR:
            continue
        if (
            our_altitude_m is not None
            and candidate.altitude_m is not None
            and abs(candidate.altitude_m - our_altitude_m) > ALTITUDE_TOLERANCE_M
        ):
            continue
        if best is None or score > best.score:
            best = Match(candidate, score, "fuzzy")
    return best
