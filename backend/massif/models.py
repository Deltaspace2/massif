"""SQLAlchemy models mirroring db/migrations/0001_init.sql.

The SQL file is the source of truth for the schema; these are the app-layer
view of it. Keep them in step by hand for now — Alembic can come later if the
schema starts churning.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from geoalchemy2 import Geometry
from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from massif.enums import (
    ExtractionMethod,
    FeatureType,
    SourceType,
    StatementType,
    StatusValue,
)


class Base(DeclarativeBase):
    pass


def _pg_enum(py_enum, name: str) -> Enum:
    # values_callable so Postgres sees the enum *values*, not the member names
    return Enum(py_enum, name=name, values_callable=lambda e: [m.value for m in e])


class Feature(Base):
    __tablename__ = "features"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    feature_type: Mapped[FeatureType] = mapped_column(
        _pg_enum(FeatureType, "feature_type"), nullable=False
    )

    name_default: Mapped[str] = mapped_column(Text, nullable=False)
    names: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    aliases: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)

    geom = mapped_column(Geometry("GEOMETRY", srid=4326), nullable=True)
    geom_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    alt_min: Mapped[int | None] = mapped_column(Integer)
    alt_max: Mapped[int | None] = mapped_column(Integer)
    massif: Mapped[str] = mapped_column(Text, nullable=False, default="mont-blanc")
    country: Mapped[str | None] = mapped_column(String(2))

    external_ids: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("features.id", ondelete="SET NULL")
    )

    notes: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    children: Mapped[list[Feature]] = relationship(back_populates="parent", remote_side=None)
    parent: Mapped[Feature | None] = relationship(back_populates="children", remote_side=[id])
    status: Mapped[FeatureStatus | None] = relationship(back_populates="feature", uselist=False)

    def __repr__(self) -> str:
        return f"<Feature {self.slug} ({self.feature_type})>"


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[SourceType] = mapped_column(
        _pg_enum(SourceType, "source_type"), nullable=False
    )
    language: Mapped[str] = mapped_column(String(2), nullable=False)
    country: Mapped[str | None] = mapped_column(String(2))

    trust_weight: Mapped[Decimal] = mapped_column(
        Numeric(3, 2), nullable=False, default=Decimal("0.50")
    )
    fetch_config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    fetch_interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=360)

    robots_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    robots_allows: Mapped[bool | None] = mapped_column(Boolean)
    last_fetch_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        return f"<Source {self.slug}>"


class Document(Base):
    """Immutable. Never deleted. Extraction runs from here."""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str | None] = mapped_column(Text)
    raw_content: Mapped[bytes | None] = mapped_column(LargeBinary)
    raw_text: Mapped[str | None] = mapped_column(Text)
    language_detected: Mapped[str | None] = mapped_column(String(2))

    http_status: Mapped[int | None] = mapped_column(Integer)
    extracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    extraction_error: Mapped[str | None] = mapped_column(Text)


class Statement(Base):
    """The normalised unit. v1 closures and v2 conditions both live here."""

    __tablename__ = "statements"
    __table_args__ = (
        CheckConstraint("severity BETWEEN 0 AND 3", name="statements_severity_check"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    feature_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("features.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL")
    )

    statement_type: Mapped[StatementType] = mapped_column(
        _pg_enum(StatementType, "statement_type"), nullable=False
    )
    status: Mapped[StatusValue] = mapped_column(
        _pg_enum(StatusValue, "status_value"), nullable=False, default=StatusValue.UNKNOWN
    )
    severity: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)

    # When a person cleared a statement a model produced. Null while it is
    # still waiting, which together with payload->needs_review is the whole
    # definition of the review queue. Kept apart from the payload because the
    # payload is what the MODEL said; this is what we decided about it.
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_note: Mapped[str | None] = mapped_column(Text)

    # When the SOURCE said it. The date on the arrêté, not the date we looked.
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # When WE last fetched the source and found this still standing. A decree
    # published a fortnight ago and re-checked a minute ago is old and current
    # at the same time; one column could not say both.
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    summary_en: Mapped[str | None] = mapped_column(Text)
    original_text: Mapped[str | None] = mapped_column(Text)
    original_language: Mapped[str | None] = mapped_column(String(2))

    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    extraction_method: Mapped[ExtractionMethod] = mapped_column(
        _pg_enum(ExtractionMethod, "extraction_method"),
        nullable=False,
        default=ExtractionMethod.RULE,
    )
    extraction_confidence: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))

    superseded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("statements.id", ondelete="SET NULL")
    )
    # THAT this statement is retired, where superseded_by says WHICH row
    # replaced it. Re-extraction is not 1:1 — an improved parser can emit
    # fewer statements than it did before, or none — so a retired statement
    # often has no successor to point at.
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FeatureStatus(Base):
    """Materialised current state. Recomputed on ingest, read by the map."""

    __tablename__ = "feature_status"

    feature_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("features.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[StatusValue] = mapped_column(
        _pg_enum(StatusValue, "status_value"), nullable=False, default=StatusValue.UNKNOWN
    )
    severity: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    summary_en: Mapped[str | None] = mapped_column(Text)

    statement_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("statements.id", ondelete="SET NULL")
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sources.id", ondelete="SET NULL")
    )

    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stale_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    feature: Mapped[Feature] = relationship(back_populates="status")


class FeatureFact(Base):
    """Directory facts about a feature — capacity, altitude, warden, water.

    Not a Statement. A statement is a claim valid over a window that can be in
    force; capacity is a property of a building. Putting these through the
    statement pipeline would enter them into the running for the status slot
    and age them with STALE_DAYS, neither of which means anything here.

    source_url is NOT NULL because refuges.info is CC BY-SA 2.0: attribution is
    a licence condition, not a courtesy.
    """

    __tablename__ = "feature_facts"
    __table_args__ = (
        UniqueConstraint("feature_id", "source_id", name="feature_facts_feature_id_source_id_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    feature_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("features.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False
    )

    external_ref: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # Theirs versus ours, same distinction as a statement's observed_at and
    # last_seen_at — and it matters more here, because directory entries are
    # edited yearly and the UI must not imply otherwise.
    source_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    match_method: Mapped[str] = mapped_column(Text, nullable=False, default="curated")
    match_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))


class UnresolvedMention(Base):
    """Review queue. A name that didn't match a feature goes here, never to
    /dev/null."""

    __tablename__ = "unresolved_mentions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE")
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sources.id", ondelete="CASCADE")
    )
    mention_text: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[str | None] = mapped_column(Text)
    candidates: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    seen_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    resolved_to: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("features.id", ondelete="SET NULL")
    )
    dismissed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class IngestRun(Base):
    __tablename__ = "ingest_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sources.id", ondelete="CASCADE")
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ok: Mapped[bool | None] = mapped_column(Boolean)
    documents_new: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    statements_new: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unresolved_new: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text)
