"""seed_phase2_origin_data

Revision ID: aca1005a8e45
Revises: 73e0bafc0692
Create Date: 2026-04-15 15:05:16.453842
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "aca1005a8e45"
down_revision: str | None = "73e0bafc0692"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Origin dictionary items (tenant_id = NULL = system-wide)

    # Grades
    op.execute("""
        INSERT INTO dictionary_items (id, type, title, description, is_active, sort_index, tenant_id, created_at, updated_at)
        VALUES
            (gen_random_uuid(), 'grade', 'Junior', 'Entry-level position', true, 0, NULL, now(), now()),
            (gen_random_uuid(), 'grade', 'Middle', 'Mid-level position', true, 1, NULL, now(), now()),
            (gen_random_uuid(), 'grade', 'Senior', 'Senior-level position', true, 2, NULL, now(), now()),
            (gen_random_uuid(), 'grade', 'Lead', 'Team lead position', true, 3, NULL, now(), now()),
            (gen_random_uuid(), 'grade', 'Principal', 'Principal/Staff level', true, 4, NULL, now(), now())
    """)

    # Specializations
    op.execute("""
        INSERT INTO dictionary_items (id, type, title, description, is_active, sort_index, tenant_id, created_at, updated_at)
        VALUES
            (gen_random_uuid(), 'specialization', 'Backend Developer', NULL, true, 0, NULL, now(), now()),
            (gen_random_uuid(), 'specialization', 'Frontend Developer', NULL, true, 1, NULL, now(), now()),
            (gen_random_uuid(), 'specialization', 'QA Engineer', NULL, true, 2, NULL, now(), now()),
            (gen_random_uuid(), 'specialization', 'Product Manager', NULL, true, 3, NULL, now(), now()),
            (gen_random_uuid(), 'specialization', 'Designer', NULL, true, 4, NULL, now(), now()),
            (gen_random_uuid(), 'specialization', 'Data Scientist', NULL, true, 5, NULL, now(), now()),
            (gen_random_uuid(), 'specialization', 'DevOps Engineer', NULL, true, 6, NULL, now(), now())
    """)

    # Competence types
    op.execute("""
        INSERT INTO dictionary_items (id, type, title, description, is_active, sort_index, tenant_id, created_at, updated_at)
        VALUES
            (gen_random_uuid(), 'competence_type', 'Hard skill', 'Technical and professional skills', true, 0, NULL, now(), now()),
            (gen_random_uuid(), 'competence_type', 'Soft skill', 'Interpersonal and communication skills', true, 1, NULL, now(), now()),
            (gen_random_uuid(), 'competence_type', 'Unique skill', 'Domain-specific unique skills', true, 2, NULL, now(), now())
    """)

    # Skill levels (system-wide, not per-tenant)
    op.execute("""
        INSERT INTO skill_levels (id, title, sort_index, created_at, updated_at)
        VALUES
            (gen_random_uuid(), 'Basic', 0, now(), now()),
            (gen_random_uuid(), 'Intermediate', 1, now(), now()),
            (gen_random_uuid(), 'Advanced', 2, now(), now())
    """)


def downgrade() -> None:
    op.execute("DELETE FROM skill_levels")
    op.execute("DELETE FROM dictionary_items WHERE tenant_id IS NULL")
