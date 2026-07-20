import uuid

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import BaseModel


class CompetenceGroup(BaseModel):
    """Hierarchical grouping of competences. tenant_id=NULL → origin."""

    __tablename__ = "competence_groups"

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("competence_groups.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    sort_index: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    can_deactivate: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )

    # lazy="raise_on_sql": identity-map hits still resolve; an SQL-emitting
    # lazy load (impossible under the async session anyway) raises clearly.
    parent: Mapped["CompetenceGroup | None"] = relationship(
        remote_side="CompetenceGroup.id",
        back_populates="children",
        lazy="raise_on_sql",
    )
    # lazy="selectin" (not "raise"): the DB FK is ON DELETE SET NULL, so
    # subtree removal on delete_group relies on the ORM delete-orphan
    # cascade, which must be able to load the children at flush time.
    children: Mapped[list["CompetenceGroup"]] = relationship(
        back_populates="parent",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    # lazy="raise": loaded explicitly where needed; rows are removed by the
    # DB-level ON DELETE CASCADE on competences.group_id (passive_deletes).
    competences: Mapped[list["Competence"]] = relationship(
        back_populates="group",
        cascade="all, delete-orphan",
        lazy="raise",
        passive_deletes=True,
    )

    @hybrid_property
    def is_root_origin(self) -> bool:
        return self.parent_id is None and self.tenant_id is None


class Competence(BaseModel):
    """Individual competence within a group. tenant_id=NULL → origin."""

    __tablename__ = "competences"

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("competence_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    competence_type_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dictionary_items.id", ondelete="SET NULL"),
        nullable=True,
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    is_published: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )

    group: Mapped["CompetenceGroup"] = relationship(
        back_populates="competences", lazy="raise_on_sql"
    )
    # lazy="raise": loaded explicitly where needed; rows are removed by the
    # DB-level ON DELETE CASCADE on the child FKs (passive_deletes).
    indicators: Mapped[list["Indicator"]] = relationship(
        back_populates="competence",
        cascade="all, delete-orphan",
        order_by="Indicator.sort_index",
        lazy="raise",
        passive_deletes=True,
    )
    materials: Mapped[list["Material"]] = relationship(
        back_populates="competence",
        cascade="all, delete-orphan",
        order_by="Material.sort_index",
        lazy="raise",
        passive_deletes=True,
    )


class SkillLevel(BaseModel):
    """Skill levels (Basic/Intermediate/Advanced + tenant-custom).

    tenant_id IS NULL → origin (system-wide, protected from edit/delete).
    tenant_id = X → custom level for tenant X.
    """

    __tablename__ = "skill_levels"
    __table_args__ = (Index("ix_skill_levels_tenant_sort", "tenant_id", "sort_index"),)

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    sort_index: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    i18n_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )


class Indicator(BaseModel):
    """Behavioral indicator for assessing a competence at a skill level."""

    __tablename__ = "indicators"

    title: Mapped[str] = mapped_column(String(600), nullable=False)
    weight: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    sort_index: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    skill_level_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("skill_levels.id", ondelete="CASCADE"),
        nullable=False,
    )
    competence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("competences.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,
    )

    competence: Mapped["Competence"] = relationship(
        back_populates="indicators", lazy="raise_on_sql"
    )
    skill_level: Mapped["SkillLevel"] = relationship(lazy="selectin")


class Material(BaseModel):
    """Learning material for a competence at a skill level."""

    __tablename__ = "materials"

    title: Mapped[str] = mapped_column(String(600), nullable=False)
    format: Mapped[str | None] = mapped_column(String(100), nullable=True)
    link: Mapped[str | None] = mapped_column(String(600), nullable=True)
    study_time: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comment: Mapped[str | None] = mapped_column(String(350), nullable=True)
    material_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    sort_index: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    skill_level_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("skill_levels.id", ondelete="CASCADE"),
        nullable=False,
    )
    competence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("competences.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,
    )

    competence: Mapped["Competence"] = relationship(
        back_populates="materials", lazy="raise_on_sql"
    )
    skill_level: Mapped["SkillLevel"] = relationship(lazy="selectin")


class MaterialSpecializationOverride(BaseModel):
    """Two-level material model: per-(material × specialization) add/hide.

    Result for an employee with specialization S and competence C:
        materials_for_pdp(C, S) =
            base_materials(C)
            \\ {m : override(m, S, mode='hide')}
            ∪ {m : override(m, S, mode='add')}
    """

    __tablename__ = "material_specialization_overrides"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "material_id",
            "specialization_id",
            "mode",
            name="uq_material_spec_override",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    material_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("materials.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    specialization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dictionary_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    mode: Mapped[str] = mapped_column(String(10), nullable=False)


class CompetenceTreeAuditLog(BaseModel):
    """Audit trail for competence tree mutations.

    Powers the «date, time, author» log on the competence library page
    (PM spec) and records AI-generation apply events (CR11).
    """

    __tablename__ = "competence_tree_audit_log"

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    element_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    element_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
