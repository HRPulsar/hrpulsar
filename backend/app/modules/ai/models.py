import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, Float, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models import BaseModel


class Embedding(BaseModel):
    __tablename__ = "embeddings"
    __table_args__ = (
        Index(
            "ix_embeddings_vector",
            "embedding",
            postgresql_using="ivfflat",
            postgresql_with={"lists": 100},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    entity_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    text_content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list] = mapped_column(Vector(1536), nullable=False)


class ModelCatalogEntry(BaseModel):
    """Platform-wide LLM model catalog (HRP-466).

    Filled by an idempotent seed from ``model_registry`` plus the daily
    ``refresh_model_catalog_task`` discovery sweep. Rows are never deleted —
    a model a provider stops listing simply stops getting ``last_seen``
    bumps. Tenant-visible pickables are ``status='approved' AND enabled``;
    freshly discovered models start as ``pending`` when billing is active
    (SaaS) and are moderated in platform admin, where ``credit_multiplier``
    is assigned (or the model is ``rejected`` — snapshots of a rejected
    family inherit the rejection).
    """

    __tablename__ = "ai_model_catalog"
    __table_args__ = (
        UniqueConstraint("provider", "model_id", name="uq_ai_model_catalog_model"),
    )

    # provider is covered by the unique constraint's leading column; the
    # pickability lookups (is_model_allowed / get_entry) filter by model_id.
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    # Curated effort-tier marker (fast|balanced|thorough) for seed rows;
    # discovered rows carry NULL unless moderation assigns one.
    tier: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="approved", server_default="approved"
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    # Moderation-assigned billing multiplier. NULL for seed rows (their
    # multiplier lives in the in-memory registry / ee credits.yaml).
    credit_multiplier: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(
        String(20), nullable=False, default="seed", server_default="seed"
    )
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
