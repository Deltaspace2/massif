"""A decision belongs to the sentence, not to the row it was recorded on.

Accepting a statement sets `reviewed_at` on that ROW. `reextract` supersedes
every statement a document produced and writes fresh ones, so the decision died
with the row and the item came back to the queue. Seen for real: the Cosmiques
statement accepted from the admin page was back after the next re-extract.

That is not wrong exactly — the new statement genuinely IS a different reading,
and silently inheriting an approval across a CHANGED reading would be worse.
The whole difficulty is telling those apart, and this file is about where the
line sits.

No second table. `statements` is never deleted, so it already holds who decided
what; a separate store of decisions would only be something else to drift.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from massif.enums import StatementType, StatusValue
from massif.ingest.base import inherit_review

DECIDED = datetime(2026, 9, 1, 10, 30, tzinfo=UTC)
EVIDENCE = "Le refuge est gardé du 15 juin au 20 septembre"

FEATURE = uuid.uuid4()
SOURCE = uuid.uuid4()


class _Statement:
    def __init__(self, **over) -> None:
        self.id = uuid.uuid4()
        self.feature_id = FEATURE
        self.source_id = SOURCE
        self.statement_type = StatementType.OPENING
        self.status = StatusValue.OPEN
        self.original_text = EVIDENCE
        self.reviewed_at = None
        self.review_note = None
        self.payload = {"needs_review": True}
        for k, v in over.items():
            setattr(self, k, v)


class _Rows(list):
    def first(self):
        return self[0] if self else None


class _Session:
    """Applies the query's own filters to the statements it was given.

    Rather than returning a canned row: the point of most of these tests is
    WHICH filters are applied, and a fake that ignores them would pass with any
    of them deleted.
    """

    def __init__(self, prior: list) -> None:
        self.prior = list(prior)
        self.queries: list = []

    def scalars(self, query):
        """Filter by the query's OWN bound values, not by constants.

        The first version of this fake compared each prior against fixed
        module constants, so a test that varied the *fresh* statement — a
        different status, a different feature — proved nothing. Reading the
        bound parameters means the filters under test are the ones actually
        applied.
        """
        self.queries.append(query)
        where = str(query.whereclause).lower()
        params = query.compile().params
        want = {
            "feature_id": params.get("feature_id_1"),
            "source_id": params.get("source_id_1"),
            "statement_type": params.get("statement_type_1"),
            "status": params.get("status_1"),
            "original_text": params.get("original_text_1"),
        }
        out = []
        for st in self.prior:
            if "reviewed_at is not null" in where and st.reviewed_at is None:
                continue
            if any(
                field in where and value is not None and getattr(st, field) != value
                for field, value in want.items()
            ):
                continue
            out.append(st)
        out.sort(key=lambda s: s.reviewed_at or DECIDED, reverse=True)
        return _Rows(out)


def _approved(**over):
    return _Statement(reviewed_at=DECIDED, review_note="checked the page", **over)


# ------------------------------------------------------------ it carries


def test_the_same_sentence_read_again_keeps_its_approval():
    fresh = _Statement()
    prior = inherit_review(_Session([_approved()]), fresh)
    assert prior is not None
    assert fresh.reviewed_at == DECIDED


def test_it_keeps_the_instant_of_the_original_decision():
    """Not now. This is that decision still standing, and re-dating it today
    would hide how old the judgement is."""
    fresh = _Statement()
    inherit_review(_Session([_approved()]), fresh)
    assert fresh.reviewed_at == DECIDED


def test_the_note_says_the_decision_was_carried_rather_than_made():
    fresh = _Statement()
    inherit_review(_Session([_approved()]), fresh)
    assert "carried forward" in fresh.review_note
    assert "checked the page" in fresh.review_note


def test_a_superseded_approval_still_counts():
    """The ordinary case, not an edge one: the prior row was superseded BY the
    re-extraction that produced this statement. If superseded rows were
    excluded there would be nothing left to inherit from and the whole thing
    would be inert."""
    old = _approved()
    old.superseded_at = DECIDED
    fresh = _Statement()
    assert inherit_review(_Session([old]), fresh) is not None
    assert fresh.reviewed_at == DECIDED


# ----------------------------------------------------- and it must not


def test_nothing_is_inherited_when_the_status_differs():
    """The dangerous one. The same sentence can support "open" on one reading
    and "closed" on a better one; carrying an approval across that would
    launder a new claim through an old decision."""
    fresh = _Statement(status=StatusValue.CLOSED)
    assert inherit_review(_Session([_approved()]), fresh) is None
    assert fresh.reviewed_at is None


def test_nothing_is_inherited_when_the_evidence_differs():
    fresh = _Statement(original_text="Le refuge est fermé")
    assert inherit_review(_Session([_approved()]), fresh) is None
    assert fresh.reviewed_at is None


def test_nothing_is_inherited_across_features():
    """Orny's page carries a sentence about the A Neuve. An approval for one
    hut is not an approval for the other."""
    fresh = _Statement(feature_id=uuid.uuid4())
    assert inherit_review(_Session([_approved()]), fresh) is None


def test_nothing_is_inherited_across_sources():
    fresh = _Statement(source_id=uuid.uuid4())
    assert inherit_review(_Session([_approved()]), fresh) is None


def test_nothing_is_inherited_across_statement_types():
    fresh = _Statement(statement_type=StatementType.CLOSURE)
    assert inherit_review(_Session([_approved()]), fresh) is None


def test_a_rejection_is_not_carried_forward():
    """A rejection is `superseded_at` with no `reviewed_at`. Re-applying one
    silently would drop a statement nobody chose to drop this time, and a wrong
    auto-rejection is invisible — where a wrong auto-approval at least shows on
    the page."""
    rejected = _Statement(reviewed_at=None, review_note="not about this hut")
    rejected.superseded_at = DECIDED
    fresh = _Statement()
    assert inherit_review(_Session([rejected]), fresh) is None
    assert fresh.reviewed_at is None


def test_a_statement_that_needs_no_review_is_left_alone():
    """Only the gated path has anything to inherit. A rule-parsed statement can
    already take a status slot."""
    fresh = _Statement(payload={})
    assert inherit_review(_Session([_approved()]), fresh) is None
    assert fresh.reviewed_at is None


def test_empty_evidence_never_matches():
    """Guard 1 in llm.py means an LLM statement always carries evidence. An
    empty span matching every other empty span would carry one approval across
    unrelated readings."""
    fresh = _Statement(original_text="")
    prior = _approved()
    prior.original_text = ""
    assert inherit_review(_Session([prior]), fresh) is None


def test_with_nothing_decided_before_it_stays_in_the_queue():
    fresh = _Statement()
    assert inherit_review(_Session([]), fresh) is None
    assert fresh.reviewed_at is None
