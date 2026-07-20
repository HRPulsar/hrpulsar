"""HRP-181 REDO: per-tenant default recruitment stages

R1 seeded a single ``vacancy_stages`` row set with ``tenant_id = NULL``
that acted as a global fallback. The HRP-181 spec wants the 9 stages
to be **per-tenant** so each tenant can override the funnel without
forking off a global row. This migration:

1. Inserts the canonical 9 stages (FR-08) for every existing tenant.
2. Remaps any ``candidate_vacancies.stage_id`` that points at the old
   global rows to the equivalent per-tenant row (code-based mapping;
   the R1 codes ``interview / evaluation / final / on_hold`` are
   renamed to ``tech_interview / manager_interview / final_interview
   / withdrew``).
3. Deletes the old global ``tenant_id IS NULL`` rows.

New tenants registered after this migration get their default stages
seeded by the ``register()`` hook in ``app.modules.auth.service``.

Revision ID: hrp181redo02
Revises: hrp181redo01
Create Date: 2026-06-07 12:30:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "hrp181redo02"
down_revision: str | None = "hrp181redo01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (code, name, sort_order, stage_type, color)
DEFAULT_STAGES = (
    ("new", "New", 10, "active", "slate"),
    ("screening", "Screening", 20, "active", "blue"),
    ("tech_interview", "Tech interview", 30, "active", "indigo"),
    ("manager_interview", "Interview with manager", 40, "active", "violet"),
    ("final_interview", "Final interview", 50, "active", "purple"),
    ("offer", "Offer", 60, "active", "amber"),
    ("hired", "Hired", 70, "terminal_positive", "emerald"),
    ("rejected", "Rejected", 80, "terminal_negative", "rose"),
    ("withdrew", "Withdrew", 90, "terminal_neutral", "gray"),
)


def upgrade() -> None:
    # Serialise concurrent runs (parallel deploys) and bound the wait
    # against tenant-table contention from live API traffic.
    op.execute("SELECT pg_advisory_xact_lock(hashtext('hrp181redo02'))")
    op.execute("SET LOCAL lock_timeout = '15s'")

    # 1. Seed each tenant with the canonical 9 stages. Idempotent on
    #    (tenant_id, code) so re-runs in a half-migrated environment
    #    don't double-insert.
    for code, name, sort_order, stage_type, color in DEFAULT_STAGES:
        is_terminal = stage_type != "active"
        op.execute(
            f"""
            INSERT INTO vacancy_stages (
                id, tenant_id, vacancy_id, name, code,
                sort_order, is_terminal, stage_type, color,
                created_at, updated_at
            )
            SELECT
                gen_random_uuid(), t.id, NULL,
                '{name}', '{code}', {sort_order},
                {str(is_terminal).lower()}, '{stage_type}', '{color}',
                now(), now()
            FROM tenants t
            WHERE NOT EXISTS (
                SELECT 1 FROM vacancy_stages vs
                WHERE vs.tenant_id = t.id
                  AND vs.vacancy_id IS NULL
                  AND vs.code = '{code}'
            )
            """
        )

    # 2. Remap candidate_vacancies pointing at old global stages.
    #    Old R1 codes → new canonical codes.
    code_remap = (
        ("new", "new"),
        ("screening", "screening"),
        ("interview", "tech_interview"),
        ("evaluation", "manager_interview"),
        ("final", "final_interview"),
        ("offer", "offer"),
        ("hired", "hired"),
        ("rejected", "rejected"),
        ("on_hold", "withdrew"),
    )
    for old_code, new_code in code_remap:
        op.execute(
            f"""
            UPDATE candidate_vacancies cv
            SET stage_id = new_stage.id
            FROM vacancy_stages old_stage,
                 vacancy_stages new_stage,
                 candidates c
            WHERE cv.stage_id = old_stage.id
              AND old_stage.tenant_id IS NULL
              AND old_stage.vacancy_id IS NULL
              AND old_stage.code = '{old_code}'
              AND cv.candidate_id = c.id
              AND new_stage.tenant_id = c.tenant_id
              AND new_stage.vacancy_id IS NULL
              AND new_stage.code = '{new_code}'
            """
        )

    # 3. Drop the now-orphaned global rows.
    op.execute(
        "DELETE FROM vacancy_stages "
        "WHERE tenant_id IS NULL AND vacancy_id IS NULL"
    )


def downgrade() -> None:
    # Restore the R1 global default set.
    op.execute(
        """
        INSERT INTO vacancy_stages
            (id, tenant_id, vacancy_id, name, code, sort_order,
             is_terminal, color, created_at, updated_at)
        VALUES
            (gen_random_uuid(), NULL, NULL, 'New', 'new', 10, false, 'slate-400', now(), now()),
            (gen_random_uuid(), NULL, NULL, 'Screening', 'screening', 20, false, 'blue-400', now(), now()),
            (gen_random_uuid(), NULL, NULL, 'Interview', 'interview', 30, false, 'cyan-500', now(), now()),
            (gen_random_uuid(), NULL, NULL, 'Evaluation', 'evaluation', 40, false, 'violet-500', now(), now()),
            (gen_random_uuid(), NULL, NULL, 'Final Stage', 'final', 50, false, 'amber-500', now(), now()),
            (gen_random_uuid(), NULL, NULL, 'Offer', 'offer', 60, false, 'emerald-500', now(), now()),
            (gen_random_uuid(), NULL, NULL, 'Hired', 'hired', 70, true, 'emerald-700', now(), now()),
            (gen_random_uuid(), NULL, NULL, 'Rejected', 'rejected', 80, true, 'rose-400', now(), now()),
            (gen_random_uuid(), NULL, NULL, 'On Hold', 'on_hold', 90, false, 'slate-300', now(), now())
        """
    )

    # Remap per-tenant back to global rows (best-effort; just for symmetry).
    op.execute(
        """
        UPDATE candidate_vacancies cv
        SET stage_id = g.id
        FROM vacancy_stages tenant_stage, vacancy_stages g
        WHERE cv.stage_id = tenant_stage.id
          AND tenant_stage.tenant_id IS NOT NULL
          AND tenant_stage.vacancy_id IS NULL
          AND g.tenant_id IS NULL
          AND g.vacancy_id IS NULL
          AND g.code = CASE tenant_stage.code
              WHEN 'tech_interview' THEN 'interview'
              WHEN 'manager_interview' THEN 'evaluation'
              WHEN 'final_interview' THEN 'final'
              WHEN 'withdrew' THEN 'on_hold'
              ELSE tenant_stage.code
          END
        """
    )

    # Drop the per-tenant default rows that we seeded.
    op.execute(
        "DELETE FROM vacancy_stages "
        "WHERE tenant_id IS NOT NULL AND vacancy_id IS NULL"
    )
