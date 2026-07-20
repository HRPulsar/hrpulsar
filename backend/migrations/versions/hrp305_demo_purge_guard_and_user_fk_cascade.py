"""HRP-305: protect non-demo tenants from DELETE + cascade user-owned FKs.

Two-layer fix for the demo-purge ForeignKeyViolation on
``pdp_comments_user_id_fkey``:

1.  ``BEFORE DELETE`` triggers on ``tenants`` and ``users`` that
    ``RAISE EXCEPTION`` when the row is not part of a demo tenant. This
    is the safety net that lets the rest of the change be safe — a
    stray ``DELETE FROM tenants WHERE id = '<prod>'`` (migration,
    psql hot-fix, admin bug) now hits a P0001 instead of silently
    cascading away years of company data. Both triggers are created
    ``ENABLE ALWAYS`` so a ``SET session_replication_role = 'replica'``
    (used by seed-reset scripts to skip FK cascades) does NOT silently
    bypass the guard.

2.  ``ON DELETE CASCADE`` / ``ON DELETE SET NULL`` on every FK pointing
    at ``users.id`` that was previously bare. Once the demo-tenant
    guard exists, the cascades only fire under the purge job's tightly
    scoped path; in prod they are unreachable.

FK plan (12 cascade + 2 set null):

* CASCADE on ``nullable=False`` (the row is meaningless without its
  author): ``notifications.recipient_id``, ``api_keys.created_by``,
  ``assessments.initiator_id``, ``assessment_groups.initiator_id``,
  ``cpas.author_id``, ``cpa_participants.user_id``, ``pdps.author_id``,
  ``pdp_comments.user_id``, ``import_jobs.initiated_by``,
  ``files.uploaded_by``, ``mass_exams.initiator_id``,
  ``talent_cards.author_id``.
* SET NULL on ``nullable=True``: ``assessments.approver_id``,
  ``pdps.reviewer_id``.

The users-trigger NOT FOUND branch is the "this is a cascade from an
already-authorized tenant DELETE" signal. When Postgres cascades the
parent ``tenants`` DELETE through ``users.tenant_id``, the parent row
has already been flagged deleted on the statement's command counter by
the time the child row's BEFORE DELETE trigger fires — so the
``SELECT … FROM tenants WHERE id = OLD.tenant_id`` inside the trigger
returns zero rows. A guard against ``OLD.tenant_id IS NULL`` runs
first so a future relaxation of ``users.tenant_id`` nullability cannot
silently disable the protection for orphan rows.

The constraint-name list is resolved against ``pg_constraint`` at
upgrade time rather than hard-coded — Postgres' default
``{table}_{column}_fkey`` convention applies on the monorepo head, but
enterprise tenants may have run manual renames in the past.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "hrp305demoguard"
down_revision: str | None = "assessanswfkcasc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (table, column, ondelete) — constraint name resolved dynamically against
# pg_constraint at upgrade time. Default convention is
# ``{table}_{column}_fkey`` but enterprise tenants may have run manual
# ALTER CONSTRAINT RENAME in the past — query rather than assume.
_USER_FKS: tuple[tuple[str, str, str], ...] = (
    ("notifications", "recipient_id", "CASCADE"),
    ("api_keys", "created_by", "CASCADE"),
    ("assessments", "initiator_id", "CASCADE"),
    ("assessments", "approver_id", "SET NULL"),
    ("assessment_groups", "initiator_id", "CASCADE"),
    ("cpas", "author_id", "CASCADE"),
    ("cpa_participants", "user_id", "CASCADE"),
    ("pdps", "author_id", "CASCADE"),
    ("pdps", "reviewer_id", "SET NULL"),
    ("pdp_comments", "user_id", "CASCADE"),
    ("import_jobs", "initiated_by", "CASCADE"),
    ("files", "uploaded_by", "CASCADE"),
    ("mass_exams", "initiator_id", "CASCADE"),
    ("talent_cards", "author_id", "CASCADE"),
)


_TENANT_GUARD_FN = "prevent_non_demo_tenant_delete"
_USER_GUARD_FN = "prevent_non_demo_user_delete"
_TENANT_GUARD_TRG = "prevent_non_demo_tenant_delete_trg"
_USER_GUARD_TRG = "prevent_non_demo_user_delete_trg"


def _resolve_fk(bind, table: str, column: str) -> tuple[str, str]:
    """Find the FK constraint name and current confdeltype on
    ``{table}.{column}`` → ``public.users.id``.

    Scoped to the ``public`` schema so cross-schema collisions
    (pg_partman partitions, ``public_old`` backup schemas, tenant-private
    schemas with same table names) don't return the wrong constraint.

    ``confdeltype`` is one byte:
        ``a`` = NO ACTION, ``r`` = RESTRICT, ``c`` = CASCADE,
        ``n`` = SET NULL, ``d`` = SET DEFAULT.
    """
    row = bind.execute(
        text(
            """
            SELECT con.conname, con.confdeltype::text
              FROM pg_constraint con
              JOIN pg_class child ON child.oid = con.conrelid
              JOIN pg_class parent ON parent.oid = con.confrelid
              JOIN pg_attribute att
                   ON att.attrelid = con.conrelid
                  AND att.attnum = ANY(con.conkey)
             WHERE con.contype = 'f'
               AND child.relname = :table
               AND child.relnamespace = 'public'::regnamespace
               AND parent.relname = 'users'
               AND parent.relnamespace = 'public'::regnamespace
               AND att.attname = :column
            """
        ),
        {"table": table, "column": column},
    ).fetchone()
    if row is None:
        raise RuntimeError(
            f"HRP-305: no FK on public.{table}.{column} → public.users.id; "
            f"cannot convert ondelete. Inspect pg_constraint manually."
        )
    return row[0], row[1]


_CONFDELTYPE_TO_ONDELETE: dict[str, str | None] = {
    "a": None,         # NO ACTION (Postgres default)
    "r": "RESTRICT",
    "c": "CASCADE",
    "n": "SET NULL",
    "d": "SET DEFAULT",
}


def upgrade() -> None:
    # --- 1. Guard triggers ---------------------------------------------
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {_TENANT_GUARD_FN}()
        RETURNS TRIGGER AS $$
        BEGIN
            IF OLD.is_demo IS NOT TRUE THEN
                RAISE EXCEPTION
                    'refusing to DELETE non-demo tenant %', OLD.id
                    USING ERRCODE = 'P0001';
            END IF;
            RETURN OLD;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {_USER_GUARD_FN}()
        RETURNS TRIGGER AS $$
        DECLARE
            tenant_is_demo BOOLEAN;
        BEGIN
            -- Defense in depth: today users.tenant_id is NOT NULL via
            -- TenantMixin, but any future migration that relaxes that
            -- would let `WHERE id = NULL` return zero rows and slip
            -- through the NOT FOUND branch below.
            IF OLD.tenant_id IS NULL THEN
                RAISE EXCEPTION
                    'refusing to DELETE user % with NULL tenant_id',
                    OLD.id
                    USING ERRCODE = 'P0001';
            END IF;
            SELECT is_demo INTO tenant_is_demo
              FROM tenants WHERE id = OLD.tenant_id;
            -- NOT FOUND: parent tenant row is already flagged deleted
            -- on this statement's command counter (cascade-from-tenant).
            -- Allow the child user row to follow.
            IF NOT FOUND THEN
                RETURN OLD;
            END IF;
            IF tenant_is_demo IS NOT TRUE THEN
                RAISE EXCEPTION
                    'refusing to DELETE user % from non-demo tenant %',
                    OLD.id, OLD.tenant_id
                    USING ERRCODE = 'P0001';
            END IF;
            RETURN OLD;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    # ENABLE ALWAYS: triggers fire under session_replication_role='replica'
    # too. The seed-reset scripts (scripts/seed_demo.py, ee/seed_saas.py)
    # set replica mode to skip FK cascades during bulk reseed; without
    # ENABLE ALWAYS the guard would silently turn off there.
    op.execute(
        f"""
        CREATE TRIGGER {_TENANT_GUARD_TRG}
        BEFORE DELETE ON tenants
        FOR EACH ROW EXECUTE FUNCTION {_TENANT_GUARD_FN}();
        """
    )
    op.execute(
        f"ALTER TABLE tenants ENABLE ALWAYS TRIGGER {_TENANT_GUARD_TRG};"
    )
    op.execute(
        f"""
        CREATE TRIGGER {_USER_GUARD_TRG}
        BEFORE DELETE ON users
        FOR EACH ROW EXECUTE FUNCTION {_USER_GUARD_FN}();
        """
    )
    op.execute(
        f"ALTER TABLE users ENABLE ALWAYS TRIGGER {_USER_GUARD_TRG};"
    )

    # --- 2. User FK ondelete sweep -------------------------------------
    # Stash the pre-upgrade confdeltype on every FK in a temp table so
    # ``downgrade()`` can put each constraint back exactly as it was —
    # an asymmetric downgrade that hard-codes NO ACTION would silently
    # rewrite a manually-customised ondelete and we can't tell the
    # difference at downgrade time.
    bind = op.get_bind()
    bind.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS hrp305_fk_snapshot (
                table_name TEXT NOT NULL,
                column_name TEXT NOT NULL,
                constraint_name TEXT NOT NULL,
                prior_confdeltype CHAR(1) NOT NULL,
                PRIMARY KEY (table_name, column_name)
            );
            """
        )
    )
    for table, column, ondelete in _USER_FKS:
        fk_name, prior = _resolve_fk(bind, table, column)
        bind.execute(
            text(
                """
                INSERT INTO hrp305_fk_snapshot
                    (table_name, column_name, constraint_name, prior_confdeltype)
                VALUES (:table, :column, :fk_name, :prior)
                ON CONFLICT (table_name, column_name) DO UPDATE SET
                    constraint_name = EXCLUDED.constraint_name,
                    prior_confdeltype = EXCLUDED.prior_confdeltype;
                """
            ),
            {"table": table, "column": column, "fk_name": fk_name, "prior": prior},
        )
        op.drop_constraint(fk_name, table, type_="foreignkey")
        op.create_foreign_key(
            fk_name,
            table,
            "users",
            [column],
            ["id"],
            ondelete=ondelete,
        )


def downgrade() -> None:
    bind = op.get_bind()
    for table, column, _ondelete in _USER_FKS:
        # Restore the exact pre-upgrade ondelete recorded in the
        # snapshot table; fall back to NO ACTION only when the snapshot
        # row is missing (downgrade run against a database that never
        # saw the upgrade-side bookkeeping — defensive but rare).
        row = bind.execute(
            text(
                """
                SELECT constraint_name, prior_confdeltype
                  FROM hrp305_fk_snapshot
                 WHERE table_name = :table AND column_name = :column
                """
            ),
            {"table": table, "column": column},
        ).fetchone()
        if row is not None:
            fk_name = row[0]
            prior_ondelete = _CONFDELTYPE_TO_ONDELETE.get(row[1])
        else:
            fk_name, _ = _resolve_fk(bind, table, column)
            prior_ondelete = None
        op.drop_constraint(fk_name, table, type_="foreignkey")
        op.create_foreign_key(
            fk_name,
            table,
            "users",
            [column],
            ["id"],
            ondelete=prior_ondelete,
        )

    op.execute(f"DROP TRIGGER IF EXISTS {_USER_GUARD_TRG} ON users;")
    op.execute(f"DROP TRIGGER IF EXISTS {_TENANT_GUARD_TRG} ON tenants;")
    op.execute(f"DROP FUNCTION IF EXISTS {_USER_GUARD_FN}();")
    op.execute(f"DROP FUNCTION IF EXISTS {_TENANT_GUARD_FN}();")
    op.execute("DROP TABLE IF EXISTS hrp305_fk_snapshot;")
