"""Primitive catalog — the platform-wide vocabulary of capabilities (HRP-748).

A primitive is an internal id of a capability a step of work requires; the
client UI never shows the word. The catalog is a platform reference with no
tenant scope: rows are seeded by migration ``v2prim01`` from
``catalog_data.PRIMITIVES`` and never deleted — a retired code keeps its row
with ``retired_in`` set so existing step and competence links keep
rendering. ``merged_into_id`` is the hook for a future code merge: coverage
counts a merged code as its target.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    or_,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import BaseModel

# ``kind`` is a column, not a prefix rule: coverage counts only cognitive
# codes (boundary ones show where the limit is), and that rule must survive
# a code rename in a later catalog version.
PRIMITIVE_KINDS = ("cognitive", "boundary")
AI_VERDICTS = ("strong", "better_than_human", "draft", "no")


class Primitive(BaseModel):
    __tablename__ = "primitives"
    __table_args__ = (
        UniqueConstraint("code", name="uq_primitives_code"),
        # The frontend keys reference.primitive.<i18n_key>: a duplicate would
        # render two codes under one label.
        UniqueConstraint("i18n_key", name="uq_primitives_i18n_key"),
        CheckConstraint(f"kind IN {PRIMITIVE_KINDS!r}", name="ck_primitives_kind"),
        CheckConstraint(
            f"ai_verdict IN {AI_VERDICTS!r}", name="ck_primitives_ai_verdict"
        ),
        Index("ix_primitives_kind", "kind"),
    )

    code: Mapped[str] = mapped_column(String(10), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    # Snapshot of the AI verdict (decision 2026-08-28): revised quarterly
    # by rewriting these three columns, without a catalog version bump.
    ai_verdict: Mapped[str] = mapped_column(String(20), nullable=False)
    ai_as_of: Mapped[date] = mapped_column(Date, nullable=False)
    ai_basis: Mapped[str] = mapped_column(String(50), nullable=False)
    # English is the render fallback; the frontend resolves
    # reference.primitive.<i18n_key>.{label,description}.
    title_en: Mapped[str] = mapped_column(String(300), nullable=False)
    scope_en: Mapped[str | None] = mapped_column(String(600), nullable=True)
    i18n_key: Mapped[str] = mapped_column(String(100), nullable=False)
    sort_index: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    introduced_in: Mapped[str] = mapped_column(String(20), nullable=False)
    retired_in: Mapped[str | None] = mapped_column(String(20), nullable=True)
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("primitives.id", ondelete="SET NULL"),
        nullable=True,
    )


# One row per competence, whoever wrote the codes. ``ai_suggested`` and the
# human statuses count the same for coverage; the status only decides whether
# the next AI run may overwrite the codes and what the internal report shows.
MAPPING_STATUSES = ("ai_suggested", "reviewed", "manual", "rejected")


class CompetenceMappingState(BaseModel):
    """Per-competence mapping state (HRP-749; decision 2026-09-09).

    Holds everything that is true of the competence's mapping as a whole:
    who decided (``status``), the text it was derived from
    (``source_fingerprint`` — a mismatch means the competence was renamed and
    must be re-mapped), and the AI verdict metadata for the internal report.
    A rejected or empty mapping keeps its row with no links, so it is
    distinguishable from a competence that was never mapped."""

    __tablename__ = "competence_mapping_states"
    __table_args__ = (
        UniqueConstraint("competence_id", name="uq_compmap_competence"),
        CheckConstraint(f"status IN {MAPPING_STATUSES!r}", name="ck_compmap_status"),
        Index("ix_compmap_tenant_status", "tenant_id", "status"),
    )

    competence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("competences.id", ondelete="CASCADE"),
        nullable=False,
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    rationale: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    mapped_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )


class CompetencePrimitive(BaseModel):
    """Competence ↔ primitive link (HRP-749): a pure N:M. Written only by
    ``primitives.mapping_service``, which keeps ``tenant_id`` mirroring
    ``competences.tenant_id`` — coverage filters here without a join. All
    per-competence metadata lives on ``CompetenceMappingState``."""

    __tablename__ = "competence_primitives"
    __table_args__ = (
        UniqueConstraint(
            "competence_id", "primitive_id", name="uq_compprim_competence_primitive"
        ),
        # Coverage walks primitive -> competences, so primitive_id leads.
        Index("ix_compprim_primitive_tenant", "primitive_id", "tenant_id"),
        Index("ix_compprim_tenant_competence", "tenant_id", "competence_id"),
    )

    competence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("competences.id", ondelete="CASCADE"),
        nullable=False,
    )
    # RESTRICT: the catalog is never deleted, only retired.
    primitive_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("primitives.id", ondelete="RESTRICT"),
        nullable=False,
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,
    )

    @classmethod
    def visible_to(cls, tenant_id: uuid.UUID):
        """The links a tenant reads: its own and the origin library's
        (``tenant_id IS NULL``). An origin competence is mapped once and
        shared, and a tenant's grade matrices may name it, so every reader
        of these links - coverage, the hire handoff, the skill prompt -
        takes both, or empties out on a tenant that works off the library."""
        return or_(cls.tenant_id == tenant_id, cls.tenant_id.is_(None))
