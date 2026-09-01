"""refuges.info hut state — the `etat` field, as statements.

The same bbox response that feeds hut FACTS also carries a state per entry, and
we were throwing it away. Every hut on the site read "unknown" as a result,
which was honest but incomplete: refuges.info does say that three of our huts
are shut, two need a key fetched first, and one has been destroyed.

    python -m massif.ingest.sources.refuges_info      # dry run, no DB

WHY A SEPARATE MODULE FROM import_hut_facts. A closure is a statement — a claim
valid over a window that can be in force — and capacity is a fact about a
building. CLAUDE.md keeps those apart on purpose, and so does this: the facts
importer writes feature_facts and never touches the status pipeline, while this
goes through the normal fetch -> store -> extract -> resolve -> recompute path
like any other source, so the state can be re-extracted from stored documents
when this parser improves.

THE FIELD. `etat` is an object with a stable `id` and a display `valeur`:

    ouverture         107 of 122   value is EMPTY
    fermeture           6          "Fermée", "Fermé", "Fermé au public"
    detruit             5          "Détruite", "Détruit"
    cle_a_recuperer     3          "Clés à récupérer", "Ouverture sur contact"

EMPTY IS NOT OPEN, and this is the whole care of this module. 107 of 122
entries carry id=ouverture with no value at all: that is the default state of a
wiki entry nobody has flagged, not a community assertion that the hut is open.
Publishing those as OPEN would turn "nobody has said anything" into "it is
fine", which is the single failure this project exists to avoid. So silence
emits nothing and the hut stays unknown.

DESTROYED IS NOT CLOSED. A closure is a hut that will reopen; "Détruite" says
the building is gone. It is emitted as a closure with severity 3 and a
needs_review flag rather than quietly, because if it is true the hut should
probably not be on the map at all, and that is a human's call. The Bivacco
della Fourche is marked destroyed and OSM still maps it — exactly the kind of
disagreement that should reach a person rather than be resolved by whichever
source we happened to read second.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from massif.enums import ExtractionMethod, StatementType, StatusValue
from massif.ingest.base import ExtractedStatement, Scraper, fetch, store_document
from massif.ingest.hut_facts import is_decoy
from massif.models import Document, Feature, FeatureFact, Source
from massif.scripts.import_hut_facts import API

# id -> (statement type, status, severity, English summary)
STATES: dict[str, tuple[StatementType, StatusValue, int, str]] = {
    "fermeture": (StatementType.CLOSURE, StatusValue.CLOSED, 2, "Closed"),
    "cle_a_recuperer": (
        StatementType.RESTRICTION,
        StatusValue.RESTRICTED,
        1,
        "Open only by prior arrangement — the key has to be collected first",
    ),
    "detruit": (
        StatementType.CLOSURE,
        StatusValue.CLOSED,
        3,
        "Recorded as destroyed — the building is reported to be gone",
    ),
}


def _modified(properties: dict) -> datetime | None:
    """When the entry was last edited, which is the only date they give.

    Not now(): a state set in 2021 is a 2021 observation, and dating it today
    would let a four-year-old wiki edit outrank this morning's arrêté.
    """
    raw = ((properties.get("date") or {}).get("derniere_modif")) or ""
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def extract(payload: dict, fetched_at: datetime) -> list[ExtractedStatement]:
    out: list[ExtractedStatement] = []
    for feature in payload.get("features") or []:
        properties = feature.get("properties") or {}
        state = properties.get("etat") or {}
        mapped = STATES.get(state.get("id") or "")
        if mapped is None:
            # id=ouverture, or an id we have never seen. Either way nobody has
            # asserted anything, so nothing is published about this hut.
            continue
        # A state with an id but no words is still a default, not a claim.
        words = (state.get("valeur") or "").strip()
        if not words:
            continue

        name = (properties.get("nom") or "").strip()
        ref = properties.get("id")
        if not name or ref is None:
            continue
        # "Ancien refuge du Goûter — Détruite" is in this response, and it
        # scores well above the resolver's floor against our live Refuge du
        # Goûter. The resolver has no decoy list — that guard lives in the hut
        # matcher — so a destroyed-building notice would have landed on the
        # working hut 20 m away. Superseded buildings are dropped here.
        if is_decoy(name):
            continue

        statement_type, status, severity, summary = mapped
        observed = _modified(properties) or fetched_at
        out.append(
            ExtractedStatement(
                feature_mention=name,
                statement_type=statement_type,
                status=status,
                severity=severity,
                observed_at=observed,
                # No window: they publish a current state, not a period. The
                # status pipeline ages it by STALE_DAYS from observed_at, which
                # is right — a closure recorded in 2021 should not still be
                # colouring a hut red today without saying how old it is.
                valid_from=None,
                valid_to=None,
                summary_en=summary,
                original_text=words,
                original_language="fr",
                extraction_method=ExtractionMethod.RULE,
                extraction_confidence=0.9,
                payload={
                    "refuges_info_id": str(ref),
                    "etat": state.get("id"),
                    "permalink": properties.get("lien"),
                    # Destroyed is a judgement a person should make, not a
                    # status we quietly paint on the map.
                    "needs_review": state.get("id") == "detruit",
                },
            )
        )
    return out


class RefugesInfoScraper(Scraper):
    slug = "refuges-info"

    def collect(
        self, session: Session, source: Source
    ) -> list[tuple[Document, list[ExtractedStatement]]]:
        response = fetch(API)
        document, is_new = store_document(session, source, API, response)
        if not is_new:
            return []
        return [(document, extract(response.json(), datetime.now(UTC)))]

    def resolve_and_build(self, session, source, document, item, resolver):
        """Resolve by refuges.info id first, and only then by name.

        Their ids are already tied to our features by the facts importer, which
        vetted each match against altitude, a decoy list and a 150 m position
        check. Re-deriving that from a name here would throw all of it away —
        and "Cabane des Conscrits" (2730 m, destroyed) scores close enough to
        our "Refuge des Conscrits" (2602 m, standing) for that to matter.
        """
        ref = (item.payload or {}).get("refuges_info_id")
        if ref:
            slug = session.scalar(
                select(Feature.slug)
                .join(FeatureFact, FeatureFact.feature_id == Feature.id)
                .where(
                    FeatureFact.source_id == source.id,
                    FeatureFact.external_ref == str(ref),
                )
            )
            if slug:
                item.feature_slug = slug
                return super().resolve_and_build(
                    session, source, document, item, resolver
                )
            # They gave an id and it is not one of ours. That is a decision the
            # facts importer already made, against altitude, a decoy list and a
            # position check — "Cabane des Conscrits" (2730 m, destroyed) is a
            # different building from our "Refuge des Conscrits" (2602 m,
            # standing), and a fuzzy name match here would overturn that
            # quietly. Queue it for a human instead of guessing.
            resolver.queue_unresolved(
                item.feature_mention,
                [],
                source_id=source.id,
                document_id=document.id,
                context=(
                    f"refuges.info {ref} is not matched to any of our huts; "
                    f"state {item.payload.get('etat')!r}"
                ),
            )
            return None
        return super().resolve_and_build(session, source, document, item, resolver)

    def extract_stored(self, document: Document) -> list[ExtractedStatement]:
        raw = document.raw_text or (document.raw_content or b"").decode("utf-8", "replace")
        return extract(json.loads(raw), document.fetched_at)


def _dump() -> int:
    """What the parser makes of the live response, writing nothing."""
    payload = fetch(API).json()
    statements = extract(payload, datetime.now(UTC))
    total = len(payload.get("features") or [])
    print(f"{total} entries in the bbox, {len(statements)} carry a state\n")
    for statement in statements:
        flag = " NEEDS REVIEW" if statement.payload.get("needs_review") else ""
        print(
            f"  {str(statement.status.value):11} {statement.feature_mention[:40]:42}"
            f" {statement.original_text!r}{flag}"
        )
    print(
        f"\n{total - len(statements)} entries said nothing, and emit nothing: "
        "an unflagged wiki entry is not an assertion that the hut is open."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_dump())
