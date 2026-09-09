"""Resolve a free-text mention to a feature.

The quiet hard problem of this project: four sources in three languages name
the same route four different ways. "Goûter", "Voie Royale", "Gouter Route",
"via normale francese" are all one thing.

Rule: an unmatched mention goes to the review queue, never to /dev/null.
Every alias added makes the next match better; every silent drop is invisible
data loss.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from rapidfuzz import fuzz, process
from sqlalchemy import select
from sqlalchemy.orm import Session

from massif.models import Feature, UnresolvedMention

# Accept outright at or above this; queue for review below it.
AUTO_ACCEPT = 88.0
# Below this we don't even offer it as a candidate.
CANDIDATE_FLOOR = 60.0

_NOISE = re.compile(
    r"\b(refuge|rifugio|refugio|h[uü]tte|cabane|bivouac|bivacco|"
    r"voie|route|via|arete|arête|cresta|couloir|glacier|ghiacciaio|"
    r"aiguille|mont|monte|pointe|punta|du|de|des|la|le|les|del|della|di|"
    # The ELIDED articles. Stripping punctuation turns "Refuge d'Argentière"
    # into "d argentiere" and leaves the orphaned "d" in the key, where it
    # costs enough similarity to drop a match under the floor: our own hut
    # scored 86 against its own alias and went to the review queue instead of
    # taking FFCAM's season. Same family as rule 1 — French that is normalised
    # almost right matches nothing, quietly.
    r"d|l)\b"
)


def normalise(text: str) -> str:
    """Casefold, strip accents, drop generic mountain nouns, squash space."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.casefold()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = _NOISE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


# Building-type words and articles only. The looseness of `normalise` above is
# a feature for FUZZY matching — "Goûter Route" should be near "Voie du
# Goûter" — but it strips the terrain nouns that are sometimes the entire
# difference between two features: "Refuge du Plan de l'Aiguille" and "Refuge
# de Plan Glacier" both normalise to "plan", and the index is first-writer-
# wins, so one hut silently owned the key and every mention of the other
# "exact-matched" it at 100. Measured across the live inventory: ELEVEN keys
# were shared by more than one feature, gouter and bossons among them.
_TYPE_NOISE = re.compile(
    r"\b(refuge|rifugio|refugio|h[uü]tte|cabane|capanna|bivouac|bivacco|"
    r"du|de|des|la|le|les|del|della|di|d|l)\b"
)


def normalise_exact(text: str) -> str:
    """Fold accents, case, punctuation and whitespace — strip no words at all.

    The first tier, because sometimes the building-type word is the entire
    difference: "Refuge du Goûter" and the route alias "Goûter" collide the
    moment "refuge" is stripped, and only one of them is a building."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.casefold()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalise_tight(text: str) -> str:
    """Like `normalise`, but terrain nouns survive.

    "refuge du plan de l'aiguille" -> "plan aiguille"
    "refuge de plan glacier"       -> "plan glacier"
    "goûter route"                 -> "gouter route", not "gouter"
    """
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.casefold()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = _TYPE_NOISE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


@dataclass(frozen=True)
class Match:
    feature_id: str
    score: float
    matched_on: str


class FeatureResolver:
    """Builds an in-memory alias index once, then resolves many mentions.

    Rebuild it after adding aliases — it does not watch the database.
    """

    def __init__(self, session: Session) -> None:
        self.session = session
        # key -> every (feature_id, form) that claims it. A key claimed by
        # more than one FEATURE is ambiguous, and an ambiguous key never
        # exact-matches: the old index was first-writer-wins, which handed the
        # whole key to whichever feature happened to load first and made the
        # others unreachable — a mention of the Refuge du Plan de l'Aiguille
        # "exact-matched" the Refuge de Plan Glacier at 100 and filed the
        # statement on the wrong hut.
        self._exact: dict[str, list[tuple[str, str]]] = {}
        self._tight: dict[str, list[tuple[str, str]]] = {}
        self._loose: dict[str, list[tuple[str, str]]] = {}
        self.reload()

    def reload(self) -> None:
        self._exact.clear()
        self._tight.clear()
        self._loose.clear()
        features = self.session.scalars(select(Feature).where(Feature.active.is_(True))).all()
        for feature in features:
            surface_forms = [feature.name_default, *(feature.names or {}).values()]
            surface_forms.extend(feature.aliases or [])
            for form in surface_forms:
                if not form:
                    continue
                tiers = (
                    (normalise_exact(form), self._exact),
                    (normalise_tight(form), self._tight),
                    (normalise(form), self._loose),
                )
                for key, index in tiers:
                    if not key:
                        continue
                    claims = index.setdefault(key, [])
                    if str(feature.id) not in {fid for fid, _f in claims}:
                        claims.append((str(feature.id), form))

    @staticmethod
    def _sole(claims: list[tuple[str, str]] | None) -> tuple[str, str] | None:
        """The key's owner, only if exactly one feature claims it."""
        if claims and len(claims) == 1:
            return claims[0]
        return None

    def resolve(self, mention: str) -> tuple[Match | None, list[Match]]:
        """Return (accepted_match_or_None, ranked_candidates).

        Exact form first (nothing stripped), then the tight key that keeps
        terrain nouns, then the loose key, then fuzzy. Each exact tier
        answers only when the key belongs to exactly one feature;
        "Montenvers" is claimed by the refuge and the railway even under the
        tight key, and no string score can say which
        building a sentence means, so ambiguity goes to a person.
        """
        for tier, key in ((self._exact, normalise_exact(mention)),
                          (self._tight, normalise_tight(mention))):
            owner = self._sole(tier.get(key))
            if owner:
                return Match(owner[0], 100.0, owner[1]), []

        key = normalise(mention)
        if not key:
            return None, []
        owner = self._sole(self._loose.get(key))
        if owner:
            return Match(owner[0], 100.0, owner[1]), []

        raw = process.extract(key, list(self._loose.keys()), scorer=fuzz.WRatio, limit=5)
        candidates = [
            Match(fid, score, form)
            for k, score, _ in raw
            if score >= CANDIDATE_FLOOR
            for fid, form in self._loose[k]
        ]
        if candidates and candidates[0].score >= AUTO_ACCEPT:
            # A tie between DIFFERENT features at the top is the ambiguity
            # case again, arrived at by another road; auto-accepting the one
            # the sort happened to put first is the first-writer-wins bug in
            # fuzzy clothing.
            tied = {c.feature_id for c in candidates if c.score == candidates[0].score}
            if len(tied) == 1:
                return candidates[0], candidates[1:]
        return None, candidates

    def queue_unresolved(
        self,
        mention: str,
        candidates: list[Match],
        *,
        source_id=None,
        document_id=None,
        context: str | None = None,
    ) -> None:
        existing = self.session.scalar(
            select(UnresolvedMention).where(
                UnresolvedMention.source_id == source_id,
                UnresolvedMention.mention_text.ilike(mention),
            )
        )
        if existing:
            existing.seen_count += 1
            from sqlalchemy import func as _f

            existing.last_seen_at = _f.now()
            return

        self.session.add(
            UnresolvedMention(
                mention_text=mention,
                context=context,
                source_id=source_id,
                document_id=document_id,
                candidates=[
                    {
                        "feature_id": c.feature_id,
                        "score": round(c.score, 1),
                        "matched_on": c.matched_on,
                    }
                    for c in candidates
                ],
            )
        )
