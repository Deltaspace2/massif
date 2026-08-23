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
    r"aiguille|mont|monte|pointe|punta|du|de|des|la|le|les|del|della|di)\b"
)


def normalise(text: str) -> str:
    """Casefold, strip accents, drop generic mountain nouns, squash space."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.casefold()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = _NOISE.sub(" ", text)
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
        self._index: dict[str, tuple[str, str]] = {}
        self.reload()

    def reload(self) -> None:
        self._index.clear()
        features = self.session.scalars(
            select(Feature).where(Feature.active.is_(True))
        ).all()
        for feature in features:
            surface_forms = [feature.name_default, *(feature.names or {}).values()]
            surface_forms.extend(feature.aliases or [])
            for form in surface_forms:
                if not form:
                    continue
                key = normalise(form)
                # first writer wins: name_default and explicit aliases beat
                # incidental translations
                if key and key not in self._index:
                    self._index[key] = (str(feature.id), form)

    def resolve(self, mention: str) -> tuple[Match | None, list[Match]]:
        """Return (accepted_match_or_None, ranked_candidates)."""
        key = normalise(mention)
        if not key:
            return None, []

        if key in self._index:
            feature_id, form = self._index[key]
            return Match(feature_id, 100.0, form), []

        raw = process.extract(
            key, list(self._index.keys()), scorer=fuzz.WRatio, limit=5
        )
        candidates = [
            Match(self._index[k][0], score, self._index[k][1])
            for k, score, _ in raw
            if score >= CANDIDATE_FLOOR
        ]
        if candidates and candidates[0].score >= AUTO_ACCEPT:
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
                    {"feature_id": c.feature_id, "score": round(c.score, 1),
                     "matched_on": c.matched_on}
                    for c in candidates
                ],
            )
        )
