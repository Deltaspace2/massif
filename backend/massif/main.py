"""Read API. The Next.js frontend renders from these."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import Depends, FastAPI, HTTPException
from geoalchemy2.shape import to_shape
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session, aliased

from massif.db import get_session
from massif.enums import StatusValue
from massif.models import Feature, FeatureStatus, IngestRun, Source, Statement

app = FastAPI(
    title="massif",
    version="0.1.0",
    description=(
        "Closure and status directory for the Mont Blanc massif. Reports what "
        "sources have published. Not a safety service."
    ),
)

DISCLAIMER = (
    "This is a directory of published notices, not a safety service. Statuses "
    "reflect what sources have said and may be out of date. Verify locally "
    "before committing to any route."
)


def _geojson(feature: Feature) -> dict | None:
    if feature.geom is None:
        return None
    return to_shape(feature.geom).__geo_interface__


# What counts as a NOTICE rather than just more data. A seasonal calendar
# entry — "scheduled summer season 2026-07-13 – 2026-09-27" — is a different
# fact from today's lift status, and correctly survives retirement, but it is
# not something to warn anyone about. Flagging it amber next to real rockfall
# notices teaches people to ignore the amber.
NOTEWORTHY_TYPES = ("closure", "restriction", "hazard_observation")


def _noteworthy(statement: Statement) -> bool:
    if (statement.payload or {}).get("schedule"):
        return False
    return (
        statement.severity >= 1
        or str(statement.statement_type) in NOTEWORTHY_TYPES
    )


def _live(now: datetime):
    """Statements that count right now: not retired, inside their validity."""
    return (
        Statement.superseded_at.is_(None),
        Statement.superseded_by.is_(None),
        (Statement.valid_from.is_(None)) | (Statement.valid_from <= now),
        (Statement.valid_to.is_(None)) | (Statement.valid_to >= now),
    )


def _other_notice_counts(session: Session, now: datetime) -> dict:
    """Per feature, how many currently-valid statements did NOT win the
    status slot.

    A single status word is a lossy summary. Saint-Gervais says the Goûter
    route is legally open; the same feature can simultaneously carry a
    rockfall notice and a demolition restriction that lost on trust weight or
    severity and are otherwise invisible. An unqualified green "open" on the
    normal route up Mont Blanc is exactly the reading this project exists to
    avoid, so the count is surfaced even when the status is not.
    """
    rows = session.execute(
        select(Statement, FeatureStatus.statement_id)
        .join(FeatureStatus, FeatureStatus.feature_id == Statement.feature_id)
        .where(*_live(now))
    ).all()

    counts: dict = {}
    for statement, winning_id in rows:
        if statement.id == winning_id or not _noteworthy(statement):
            continue
        counts[statement.feature_id] = counts.get(statement.feature_id, 0) + 1
    return counts


def _season_status(statements: list, has_schedule: bool) -> dict:
    """Is this thing available THIS SEASON, ignoring the hour of the day?

    The site was colouring by operational status — "is it turning right now" —
    which is the wrong question for someone planning a trip. At 03:00 every
    lift in the massif reads closed, the whole map goes grey, and a genuine
    seasonal closure is indistinguishable from nightfall.

    Season status ignores operational_status entirely and reads only the
    facts that survive the night: decreed closures, advisories, and whether a
    published season covers today.

    A feature that publishes seasons and has none covering today is out of
    season — that is a real answer, not missing data, and it is the one
    Grands Montets needs.
    """
    blocking = [
        st for st in statements
        if str(st.statement_type) in ("closure", "restriction")
    ]
    if blocking:
        worst = max(blocking, key=lambda st: st.severity)
        return {
            "value": (
                StatusValue.CLOSED
                if str(worst.statement_type) == "closure"
                else StatusValue.RESTRICTED
            ),
            "reason": worst.summary_en,
            "kind": "notice",
        }

    live_schedule = [st for st in statements if (st.payload or {}).get("schedule")]
    if live_schedule:
        return {
            "value": StatusValue.OPEN,
            "reason": live_schedule[0].summary_en,
            "kind": "in_season",
        }

    if has_schedule:
        return {
            "value": StatusValue.CLOSED,
            "reason": "not running this season",
            "kind": "out_of_season",
        }

    return {"value": StatusValue.UNKNOWN, "reason": None, "kind": None}


def _feature_dict(
    feature: Feature,
    status: FeatureStatus | None,
    statement: Statement | None = None,
    parent_slug: str | None = None,
    other_notices: int = 0,
    season: dict | None = None,
) -> dict:
    now = datetime.now(UTC)
    payload = (statement.payload if statement else None) or {}
    return {
        "slug": feature.slug,
        "type": feature.feature_type,
        # Lets a client separate sectors from the individual machines inside
        # them. Without it every auto-created lift competes with its parent.
        "parent_slug": parent_slug,
        "name": feature.name_default,
        "names": feature.names,
        "alt_min": feature.alt_min,
        "alt_max": feature.alt_max,
        "country": feature.country,
        "geometry": _geojson(feature),
        "geom_verified": feature.geom_verified,
        "status": {
            "value": status.status if status else StatusValue.UNKNOWN,
            "severity": status.severity if status else 0,
            "summary": status.summary_en if status else None,
            "observed_at": status.observed_at if status else None,
            "stale": bool(
                status and status.stale_after and status.stale_after < now
            ),
            # "outside_hours" means routine: shut because it is night or out
            # of season. The map must render that quietly. Anything else is
            # a closure worth shouting about.
            "closure_kind": payload.get("closure_kind"),
            "counts": payload.get("counts"),
            "altitude_m": payload.get("altitude_m"),
            "lifts": payload.get("lifts"),
            # Currently-valid statements that did not win the status slot.
            # Never let one word be the whole story.
            "other_notices": other_notices,
        },
        # What a trip planner actually asks. status is "right now"; this is
        # "this season", and it is what the UI colours by.
        "season": season
        or {"value": StatusValue.UNKNOWN, "reason": None, "kind": None},
    }


@app.get("/health")
def health(session: Session = Depends(get_session)) -> dict:
    """Last successful ingest, front and centre. Abandonment is the real
    failure mode — a site that stopped updating in November is worse than no
    site, because people trust it anyway."""
    last_ok = session.scalar(
        select(func.max(IngestRun.finished_at)).where(IngestRun.ok.is_(True))
    )
    return {
        "ok": True,
        "last_successful_ingest": last_ok,
        "features": session.scalar(select(func.count()).select_from(Feature)),
        "disclaimer": DISCLAIMER,
    }


@app.get("/features")
def list_features(
    feature_type: str | None = None,
    status: StatusValue | None = None,
    session: Session = Depends(get_session),
) -> dict:
    Parent = aliased(Feature)
    query = (
        select(Feature, FeatureStatus, Statement, Parent.slug)
        .outerjoin(FeatureStatus, FeatureStatus.feature_id == Feature.id)
        .outerjoin(Statement, Statement.id == FeatureStatus.statement_id)
        .outerjoin(Parent, Parent.id == Feature.parent_id)
        .where(Feature.active.is_(True))
    )
    if feature_type:
        query = query.where(Feature.feature_type == feature_type)
    if status:
        query = query.where(FeatureStatus.status == status)

    rows = session.execute(query).all()
    now = datetime.now(UTC)
    others = _other_notice_counts(session, now)

    # Every currently-valid statement, grouped by feature, so season status
    # can be derived without a query per feature.
    live_by_feature: dict = {}
    for statement in session.scalars(select(Statement).where(*_live(now))):
        live_by_feature.setdefault(statement.feature_id, []).append(statement)

    # Which features publish seasons at all — an empty result then means
    # "out of season" rather than "we have no idea".
    schedule_features = {
        fid
        for (fid,) in session.execute(
            select(Statement.feature_id)
            .where(Statement.payload["schedule"].astext == "true")
            .distinct()
        )
    }
    return {
        "count": len(rows),
        "features": [
            _feature_dict(
                f, st, stmt, parent, others.get(f.id, 0),
                _season_status(
                    live_by_feature.get(f.id, []), f.id in schedule_features
                ),
            )
            for f, st, stmt, parent in rows
        ],
        "disclaimer": DISCLAIMER,
    }


@app.get("/features/{slug}")
def get_feature(slug: str, session: Session = Depends(get_session)) -> dict:
    row = session.execute(
        select(Feature, FeatureStatus, Statement)
        .outerjoin(FeatureStatus, FeatureStatus.feature_id == Feature.id)
        .outerjoin(Statement, Statement.id == FeatureStatus.statement_id)
        .where(Feature.slug == slug)
    ).first()
    if row is None:
        raise HTTPException(404, "no such feature")
    feature, status, current = row

    history = session.execute(
        select(Statement, Source)
        .join(Source, Source.id == Statement.source_id)
        .where(
            Statement.feature_id == feature.id,
            # Retired by re-extraction: the parser that produced these has
            # since retracted them. They stay in the table as a record of
            # what we used to think, but we never show them as notices.
            Statement.superseded_at.is_(None),
            Statement.superseded_by.is_(None),
        )
        .order_by(desc(Statement.observed_at))
        .limit(50)
    ).all()

    now = datetime.now(UTC)

    # Everything currently valid that is NOT the winning statement. These are
    # the notices a single status word discards — a legal opening can sit on
    # the same feature as a live rockfall warning, and only one of them gets
    # to be the colour of the card.
    winning = status.statement_id if status else None
    others = [
        (st, src)
        for st, src in session.execute(
            select(Statement, Source)
            .join(Source, Source.id == Statement.source_id)
            .where(Statement.feature_id == feature.id, *_live(now))
            .order_by(desc(Statement.severity), desc(Statement.observed_at))
        ).all()
        if st.id != winning and _noteworthy(st)
    ]

    live_here = list(
        session.scalars(
            select(Statement).where(Statement.feature_id == feature.id, *_live(now))
        )
    )
    publishes_seasons = bool(
        session.scalar(
            select(Statement.id).where(
                Statement.feature_id == feature.id,
                Statement.payload["schedule"].astext == "true",
            )
        )
    )

    parent = session.get(Feature, feature.parent_id) if feature.parent_id else None
    payload = _feature_dict(
        feature, status, current, parent.slug if parent else None, len(others),
        _season_status(live_here, publishes_seasons),
    )

    payload["other_notices"] = [
        {
            "type": st.statement_type,
            "status": st.status,
            "severity": st.severity,
            "observed_at": st.observed_at,
            "valid_from": st.valid_from,
            "valid_to": st.valid_to,
            "summary": st.summary_en,
            "original_text": st.original_text,
            "original_language": st.original_language,
            "advisory": bool((st.payload or {}).get("advisory")),
            "source": {"name": src.name, "url": src.url, "type": src.source_type},
        }
        for st, src in others
    ]

    payload["parent"] = (
        {"slug": parent.slug, "name": parent.name_default} if parent else None
    )
    payload["children"] = [
        {
            "slug": child.slug,
            "name": child.name_default,
            "status": child_status.status if child_status else StatusValue.UNKNOWN,
            "summary": child_status.summary_en if child_status else None,
        }
        for child, child_status in session.execute(
            select(Feature, FeatureStatus)
            .outerjoin(FeatureStatus, FeatureStatus.feature_id == Feature.id)
            .where(Feature.parent_id == feature.id)
            .order_by(Feature.name_default)
        ).all()
    ]
    payload["history"] = [
        {
            "type": st.statement_type,
            "status": st.status,
            "severity": st.severity,
            "observed_at": st.observed_at,
            "valid_from": st.valid_from,
            "valid_to": st.valid_to,
            "summary": st.summary_en,
            "original_text": st.original_text,
            "original_language": st.original_language,
            # never present an aggregation as our own authority
            "source": {"name": src.name, "url": src.url, "type": src.source_type},
        }
        for st, src in history
    ]
    return payload


@app.get("/feed")
def feed(limit: int = 50, session: Session = Depends(get_session)) -> dict:
    """What changed, reverse-chronological. The page people bookmark."""
    rows = session.execute(
        select(Statement, Feature, Source)
        .join(Feature, Feature.id == Statement.feature_id)
        .join(Source, Source.id == Statement.source_id)
        # Retracted by a later re-extraction; never in the feed.
        .where(
            Statement.superseded_at.is_(None),
            Statement.superseded_by.is_(None),
        )
        .order_by(desc(Statement.observed_at))
        .limit(min(limit, 200))
    ).all()
    return {
        "items": [
            {
                "feature": {"slug": f.slug, "name": f.name_default, "type": f.feature_type},
                "status": st.status,
                "severity": st.severity,
                "summary": st.summary_en,
                "observed_at": st.observed_at,
                "source": {"name": src.name, "url": src.url},
            }
            for st, f, src in rows
        ],
        "disclaimer": DISCLAIMER,
    }
