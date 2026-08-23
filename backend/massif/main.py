"""Read API. The Next.js frontend renders from these."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import Depends, FastAPI, HTTPException
from geoalchemy2.shape import to_shape
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

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


def _feature_dict(feature: Feature, status: FeatureStatus | None) -> dict:
    now = datetime.now(UTC)
    return {
        "slug": feature.slug,
        "type": feature.feature_type,
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
        },
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
    query = (
        select(Feature, FeatureStatus)
        .outerjoin(FeatureStatus, FeatureStatus.feature_id == Feature.id)
        .where(Feature.active.is_(True))
    )
    if feature_type:
        query = query.where(Feature.feature_type == feature_type)
    if status:
        query = query.where(FeatureStatus.status == status)

    rows = session.execute(query).all()
    return {
        "count": len(rows),
        "features": [_feature_dict(f, s) for f, s in rows],
        "disclaimer": DISCLAIMER,
    }


@app.get("/features/{slug}")
def get_feature(slug: str, session: Session = Depends(get_session)) -> dict:
    row = session.execute(
        select(Feature, FeatureStatus)
        .outerjoin(FeatureStatus, FeatureStatus.feature_id == Feature.id)
        .where(Feature.slug == slug)
    ).first()
    if row is None:
        raise HTTPException(404, "no such feature")
    feature, status = row

    history = session.execute(
        select(Statement, Source)
        .join(Source, Source.id == Statement.source_id)
        .where(Statement.feature_id == feature.id)
        .order_by(desc(Statement.observed_at))
        .limit(50)
    ).all()

    payload = _feature_dict(feature, status)
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
