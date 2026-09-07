"""Writing and editing statements by hand, from the admin panel.

Two jobs the review queue could not do. It only ever handled things a scraper
had already produced: you could accept, reject or override a statement on its
way in, and after that it was fixed until the source changed. There was no way
to say something no source publishes, and no way to correct something already
live.

`seeds/sources.yaml` has carried an active `manual` source with no scraper
since the beginning — "admin-entered statements: hut closures phoned in,
things seen in person" — so hand-written notices were always meant to be a
first-class source with a trust weight and an audit trail, rather than an
untraceable edit.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from massif.admin import apply_override, new_statement
from massif.enums import StatementType, StatusValue


class _Source:
    id = "11111111-1111-1111-1111-111111111111"
    slug = "manual"


class _Feature:
    id = "22222222-2222-2222-2222-222222222222"
    slug = "refuge-de-test"


NOW = datetime(2026, 9, 7, 12, 30, tzinfo=UTC)


def _fields(**over) -> dict[str, str]:
    base = {
        "statement_type": "closure",
        "status": "closed",
        "valid_from": "2026-09-10",
        "valid_to": "2026-09-20",
        "summary": "Shut for works — the warden phoned",
    }
    base.update(over)
    return {k: v for k, v in base.items() if v is not None}


# ----------------------------------------------------------- what it writes


def test_a_hand_written_statement_carries_the_manual_source_and_needs_no_review():
    """A person wrote it. Sending it to the review queue would ask them to
    approve their own sentence, and it would sit there for ever if they did
    not — invisible, because the gate keeps unreviewed statements out of the
    status slot entirely."""
    st = new_statement(_Feature, _Source, _fields(), now=NOW)
    assert st.source_id == _Source.id
    assert st.feature_id == _Feature.id
    assert st.status is StatusValue.CLOSED
    assert st.statement_type is StatementType.CLOSURE
    assert st.reviewed_at is not None, "a human writing it IS the review"
    assert not (st.payload or {}).get("needs_review")


def test_it_records_that_a_person_wrote_it_rather_than_a_parser():
    st = new_statement(_Feature, _Source, _fields(), now=NOW)
    assert (st.payload or {}).get("hand_written") is True


def test_both_clocks_are_now_because_a_person_just_said_it():
    """Rule 10 — `observed_at` is when the source published and `last_seen_at`
    is when we last confirmed it still stands. For a hand-written note those
    are the same instant, and it is now."""
    st = new_statement(_Feature, _Source, _fields(), now=NOW)
    assert st.observed_at == NOW
    assert st.last_seen_at == NOW


# ---------------------------------------------------------- what it refuses


def test_rule_3_applies_to_a_person_exactly_as_it_does_to_a_model():
    """An undated `closed` sits on the map for ever: `recompute_feature` reads
    null validity bounds as currently valid. Being typed by a human does not
    make it expire."""
    with pytest.raises(HTTPException) as refusal:
        new_statement(_Feature, _Source, _fields(valid_from=None, valid_to=None), now=NOW)
    assert refusal.value.status_code == 400
    assert "window" in str(refusal.value.detail)


def test_a_standing_state_still_needs_no_dates():
    """`unstaffed` and `unknown` assert nothing about the present, so they are
    exempt — the same exemption `apply_override` already makes, from the same
    frozenset, so the two cannot drift apart."""
    st = new_statement(
        _Feature,
        _Source,
        _fields(
            status="unstaffed",
            statement_type="operational_status",
            valid_from=None,
            valid_to=None,
        ),
        now=NOW,
    )
    assert st.status is StatusValue.UNSTAFFED


def test_a_statement_with_no_words_is_refused():
    """The summary is what the site prints. A blank one publishes a coloured
    status with nothing underneath it."""
    with pytest.raises(HTTPException):
        new_statement(_Feature, _Source, _fields(summary=""), now=NOW)


def test_an_unknown_status_or_type_is_refused_rather_than_guessed():
    for bad in ({"status": "ajar"}, {"statement_type": "vibes"}):
        with pytest.raises(HTTPException):
            new_statement(_Feature, _Source, _fields(**bad), now=NOW)


# ------------------------------------------- correcting something already live


class _Live:
    """A statement a scraper wrote, currently in force."""

    def __init__(self) -> None:
        self.status = StatusValue.OPEN
        self.statement_type = StatementType.OPENING
        self.summary_en = "what the parser made of it"
        self.valid_from = datetime(2026, 9, 1, tzinfo=UTC)
        self.valid_to = datetime(2026, 9, 30, tzinfo=UTC)
        self.payload: dict = {}
        self.reviewed_at = None


def test_a_live_statement_is_corrected_through_the_same_rules():
    """Editing after the fact reuses `apply_override`, so wording, dates and
    rule 3 behave exactly as they do on the review card. One code path, or the
    two drift and only one of them has tests."""
    live = _Live()
    changed = apply_override(live, {"summary": "what a person knows", "status": "restricted"})
    assert live.summary_en == "what a person knows"
    assert live.status is StatusValue.RESTRICTED
    assert "summary" in changed and "status" in changed
    # The parser's wording survives as the record of what was actually read.
    assert live.payload["model_summary"] == "what the parser made of it"
