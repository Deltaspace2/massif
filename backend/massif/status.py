"""Recompute materialised feature_status from statements.

Resolution rule: highest source trust_weight, then most recent observed_at,
then highest severity.

Staleness is displayed, not hidden. Being confidently out of date is what
destroys trust in a conditions site — worse than being wrong, because a stale
"open" reads as clearance.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from massif.config import settings
from massif.enums import StatusValue
from massif.models import FeatureStatus, Source, Statement

# How long a statement of each type stays presentable before it is greyed out.
STALE_DAYS: dict[str, int] = {
    "operational_status": 1,   # lift status is worthless the next morning
    "closure": 90,             # an arrêté holds until revoked
    "restriction": 90,
    "opening": 30,
    "condition": 14,           # v2
    "hazard_observation": 7,   # v2
}


# Shelf life by SOURCE, where the type alone gets it wrong. STALE_DAYS was
# tuned for notices that are published on a date and then stop being news; some
# sources instead maintain a standing state that is meant to hold until someone
# edits it, and judging those by an arrêté's 90 days mislabels them.
#
# refuges.info's `etat` is exactly that: a wiki field saying what a hut is like
# now, carrying no date of its own, so the best date available is when a
# volunteer last touched the page. A closure edited 14 months ago is genuinely
# weaker evidence than one published last week — but it is a standing statement
# rather than an expired one, and 90 days flagged three huts as old purely for
# not having been edited recently.
#
# A year is the judgement: long enough that an unedited standing state is not
# called old for the sake of it, short enough that a page nobody has touched in
# over a year stops speaking for the present.
SOURCE_STALE_DAYS: dict[str, int] = {
    "refuges-info": 365,
}


def stale_days_for(statement: Statement, session: Session) -> int:
    """How long this statement stays presentable.

    Source first, then statement type, then the configured default. Source wins
    because it is the more specific fact: what KIND of thing a source publishes
    outranks what kind of notice it happens to be.
    """
    source_slug = session.scalar(
        select(Source.slug).where(Source.id == statement.source_id)
    )
    if source_slug in SOURCE_STALE_DAYS:
        return SOURCE_STALE_DAYS[source_slug]
    return STALE_DAYS.get(str(statement.statement_type), settings.default_stale_days)


def recompute_feature(session: Session, feature_id: uuid.UUID) -> FeatureStatus:
    now = datetime.now(UTC)

    rows = session.execute(
        select(Statement, Source.trust_weight)
        .join(Source, Source.id == Statement.source_id)
        .where(
            Statement.feature_id == feature_id,
            Statement.superseded_by.is_(None),
            # Retired by re-extraction. Checked alongside superseded_by rather
            # than replacing it: a row excluded before must stay excluded.
            Statement.superseded_at.is_(None),
            (Statement.valid_from.is_(None)) | (Statement.valid_from <= now),
            (Statement.valid_to.is_(None)) | (Statement.valid_to >= now),
        )
    ).all()

    status = session.get(FeatureStatus, feature_id)
    if status is None:
        status = FeatureStatus(feature_id=feature_id)
        session.add(status)

    if not rows:
        status.status = StatusValue.UNKNOWN
        status.severity = 0
        status.summary_en = None
        status.statement_id = None
        status.source_id = None
        status.observed_at = None
        status.last_seen_at = None
        status.stale_after = None
        status.computed_at = now
        return status

    def rank(row) -> tuple:
        statement, trust = row
        return (float(trust), statement.observed_at, statement.severity)

    winner, _trust = max(rows, key=rank)

    stale_days = stale_days_for(winner, session)

    status.status = winner.status
    status.severity = winner.severity
    status.summary_en = winner.summary_en
    status.statement_id = winner.id
    status.source_id = winner.source_id
    status.observed_at = winner.observed_at
    status.last_seen_at = winner.last_seen_at
    status.stale_after = winner.observed_at + timedelta(days=stale_days)
    status.computed_at = now
    return status


def recompute_many(session: Session, feature_ids: set[uuid.UUID]) -> int:
    for feature_id in feature_ids:
        recompute_feature(session, feature_id)
    return len(feature_ids)


def is_stale(status: FeatureStatus, at: datetime | None = None) -> bool:
    at = at or datetime.now(UTC)
    return status.stale_after is not None and status.stale_after < at


def active_advisories(
    session: Session, feature_ids: set[uuid.UUID], at: datetime | None = None
) -> dict[uuid.UUID, list[Statement]]:
    """Currently-valid warnings that did NOT win the status slot.

    Trust weight decides open versus closed, and it should: legal authority
    outranks a safety office on whether a route is legally shut. But losing
    that contest must not silence a warning.

    The case this exists for, live in the database:

        Saint-Gervais (trust 1.00): the Goûter route is open.
        OHM (trust 0.85): "Réouverture « administrative » ... Cela ne signifie
        pas une disparition des risques… Différer son projet d'ascension."

    Both true. Resolution correctly shows "open" — and a page that stops there
    is a technically accurate answer that reads as clearance on the
    most-climbed route in the Alps, in a season the local safety office is
    telling people to stay off it.

    So: everything valid right now, carrying severity, that is not the winner.
    """
    if not feature_ids:
        return {}
    at = at or datetime.now(UTC)

    winners = {
        row[0]
        for row in session.execute(
            select(FeatureStatus.statement_id).where(
                FeatureStatus.feature_id.in_(feature_ids),
                FeatureStatus.statement_id.is_not(None),
            )
        ).all()
    }

    rows = session.scalars(
        select(Statement)
        .where(
            Statement.feature_id.in_(feature_ids),
            Statement.severity >= 1,
            Statement.superseded_by.is_(None),
            Statement.superseded_at.is_(None),
            (Statement.valid_from.is_(None)) | (Statement.valid_from <= at),
            (Statement.valid_to.is_(None)) | (Statement.valid_to >= at),
        )
        .order_by(Statement.severity.desc(), Statement.observed_at.desc())
    ).all()

    out: dict[uuid.UUID, list[Statement]] = {}
    for statement in rows:
        if statement.id in winners:
            continue
        out.setdefault(statement.feature_id, []).append(statement)
    return out
