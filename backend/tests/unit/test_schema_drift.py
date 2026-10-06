"""HRP-540: guard that SQLAlchemy models and Alembic migrations agree.

``tests/conftest.py`` builds the unit-test schema with
``Base.metadata.create_all`` — migrations never run there, so a model
extended without a matching migration passes the whole suite and only
breaks in production (HRP-539 lived that way from May to August).

This module closes the gap: it provisions a throwaway database, runs
``alembic upgrade heads`` into it, and diffs the resulting schema against
``Base.metadata`` with ``alembic.autogenerate.compare_metadata``.

The test is marked ``migrations`` and excluded from the default run
(``addopts`` in ``pyproject.toml``) because it costs a full migration
replay; CI runs it as its own step. Run it locally with::

    pytest tests/unit/test_schema_drift.py -m migrations

Pre-existing, deliberately tolerated differences live in
``ALLOWED_DRIFT``. Every entry is a case where the database is *wider*
than the model (a larger int, a stricter NOT NULL, an extra index), so
the model can never write a value the column rejects. Closing them needs
real migrations, which is a separate change — the point of this guard is
that **new** drift cannot be added silently.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from app.config import settings
from app.database import Base, import_all_models

# Enterprise models, when this checkout has them. migrations/env.py does the
# same soft import; this file is on the sync guard's EE-import allowlist for
# exactly that reason (see scripts/sync_repos.sh).
try:
    from ee import models as ee_models  # noqa: F401

    EE_MODELS_AVAILABLE = True
except ImportError:  # community checkout — backend/ee is not synced
    EE_MODELS_AVAILABLE = False

pytestmark = pytest.mark.migrations

BACKEND_DIR = Path(__file__).resolve().parents[2]

# Dedicated database: tests/conftest.py drops and rebuilds the public
# schema of ``hrpulsar_test`` on first use of the ``db`` fixture, which
# would race a migrated schema living in the same database.
#
# The name carries a per-process suffix: a fixed one would have two
# pytest-xdist workers dropping and recreating each other's database
# mid-run. Outside xdist the pid keeps concurrent local runs apart.
MIGRATIONS_DB_NAME = (
    f"hrpulsar_migrations_test_"
    f"{os.environ.get('PYTEST_XDIST_WORKER') or f'pid{os.getpid()}'}"
)


def _server_url(database: str) -> str:
    """Swap the database name in the configured async URL.

    ``make_url`` keeps query parameters (``?sslmode=require``) that naive
    string surgery on the last path segment would drop.
    """
    return (
        sa.make_url(settings.database_url)
        .set(database=database)
        .render_as_string(hide_password=False)
    )


def _sync(url: str) -> str:
    return url.replace("+asyncpg", "+psycopg2")


# ---------------------------------------------------------------------------
# Accepted pre-existing drift
# ---------------------------------------------------------------------------
#
# Keys are the normalised diff identities produced by ``_diff_key``. Values
# are the reason the difference is tolerated. Do NOT add entries here to
# silence a model change you just made — write the migration instead.

ALLOWED_DRIFT: dict[str, str] = {}

# --- Column type: DB wider than the model ---------------------------------
# The database accepts every value the model can produce; narrowing the
# column is the risky direction, so these wait for deliberate migrations.
for _key in (
    "modify_type:interviews.file_size_bytes:db=BIGINT():model=Integer()",
    "modify_type:upload_sessions.total_size:db=BIGINT():model=Integer()",
    "modify_type:upload_sessions.uploaded_bytes:db=BIGINT():model=Integer()",
):
    ALLOWED_DRIFT[_key] = "DB BIGINT vs model INTEGER — DB is wider."

# --- Nullability: DB stricter than the model ------------------------------
# Both columns carry a server_default, so every insert populates them and
# the model can never produce the NULL its annotation permits.
for _key in (
    "modify_nullable:vacancy_grades.created_at:db=False:model=True",
    "modify_nullable:vacancy_specializations.created_at:db=False:model=True",
):
    ALLOWED_DRIFT[_key] = "DB NOT NULL vs model nullable — server_default fills it."

# --- TenantMixin's index, superseded by a composite (HRP-581) -------------
# ``TenantMixin`` declares ``index=True`` on every tenant-scoped table, so
# these four models ask for a plain ``tenant_id`` index. Their migrations
# deliberately created something better instead — a composite that *leads*
# with ``tenant_id`` (``(tenant_id, created_at DESC)``, or a UNIQUE on
# ``tenant_id`` alone for the retention config). Postgres serves both the
# tenant-scoped reads and the ON DELETE CASCADE check from that leading
# column, so adding the plain index back would only slow writes on the
# highest-write tables in the system.
#
# This is a reviewed decision, not a backlog item: HRP-581 walked all 42
# model-only indexes, created the 14 that earn their keep (migration
# ``hrp581recidx``) and dropped ``index=True`` from the other 24. These
# four cannot be dropped from the model without overriding the mixin per
# table, which would break a platform-wide invariant to save four lines.
for _key in (
    "add_index:gdpr_erasure_log.ix_gdpr_erasure_log_tenant_id",
    "add_index:gdpr_export_requests.ix_gdpr_export_requests_tenant_id",
    "add_index:recruitment_audit_log.ix_recruitment_audit_log_tenant_id",
    "add_index:recruitment_retention_configs.ix_recruitment_retention_configs_tenant_id",
):
    ALLOWED_DRIFT[_key] = (
        "TenantMixin's plain tenant_id index — a composite leading with "
        "tenant_id already covers it."
    )

# --- Indexes created by a migration but not declared on the model ---------
# Composite / partial / expression indexes added for specific queries and
# never back-ported to the model definition. Dropping them would regress
# those queries, so they are kept and the models stay silent about them.
for _key in (
    "remove_constraint:external_reviewers.external_reviewers_token_key",
    "remove_constraint:invitations.invitations_token_key",
    "remove_index:answer_scale_levels.ux_scale_level_code_per_scale",
    "remove_index:audit_logs.ix_audit_logs_created_at",
    "remove_index:candidate_files.ix_candidate_files_detached_recent",
    "remove_index:consent_requests.ix_consent_requests_token",
    "remove_index:consent_templates.ix_consent_templates_active_unique",
    "remove_index:consolidated_reports.ix_consolidated_reports_vacancy_created",
    "remove_index:gdpr_erasure_log.ix_gdpr_erasure_log_subject",
    "remove_index:gdpr_erasure_log.ix_gdpr_erasure_log_tenant",
    "remove_index:gdpr_export_requests.ix_gdpr_export_requests_subject",
    "remove_index:gdpr_export_requests.ix_gdpr_export_requests_tenant",
    "remove_index:interview_interviewers.ix_interview_interviewers_user_id",
    "remove_index:interviews.ix_interviews_av_status",
    "remove_index:interviews.ix_interviews_tenant_analysis_status",
    "remove_index:interviews.ix_interviews_tenant_transcription_status",
    "remove_index:public_assessment_ip_blocks.ix_public_assessment_ip_blocks_until",
    "remove_index:recruitment_audit_log.ix_recruitment_audit_log_entity",
    "remove_index:recruitment_audit_log.ix_recruitment_audit_log_tenant_created",
    "remove_index:recruitment_retention_configs.ix_recruitment_retention_configs_tenant_unique",
    "remove_index:signup_requests.ix_signup_requests_status",
    "remove_index:signup_requests.uq_signup_requests_email_lower",
    "remove_index:tenant_ai_settings.ix_tenant_ai_settings_tenant_id",
    "remove_index:tenants.ix_tenants_demo_expires_at",
    "remove_index:upload_sessions.ix_upload_sessions_status_expires",
    "remove_index:vacancy_grades.ix_vacancy_grades_vacancy_id",
    "remove_index:vacancy_specializations.ix_vacancy_specializations_vacancy_id",
):
    ALLOWED_DRIFT[_key] = "Index exists in DB by migration, undeclared on the model."

# --- Migration bookkeeping table ------------------------------------------
ALLOWED_DRIFT["remove_table:hrp305_fk_snapshot"] = (
    "Scratch table hrp305_demo_purge_guard_and_user_fk_cascade creates to "
    "make its own downgrade reversible — deliberately has no model."
)

# --- Community checkout: enterprise models absent, their tables are not ---
# audit_logs is created by CORE migration f1a2b3c4d5e6 (which syncs to the
# public repo) but its model lives in ee/models.py (which does not). So a
# community build legitimately has the table with no model behind it. The
# migration is deliberately NOT moved: it is already applied on self-hosted
# installs and rewriting history there would break them.
if not EE_MODELS_AVAILABLE:
    for _key in (
        "remove_table:audit_logs",
        "remove_index:audit_logs.ix_audit_logs_actor_id",
        "remove_index:audit_logs.ix_audit_logs_action",
    ):
        ALLOWED_DRIFT[_key] = (
            "Community build: audit_logs is created by a core migration but "
            "modelled only in ee/models.py."
        )

del _key


# ---------------------------------------------------------------------------
# Diff normalisation
# ---------------------------------------------------------------------------


def _table_of(obj: Any) -> str:
    name = getattr(obj, "table_name", None)
    if name:
        return str(name)
    table = getattr(obj, "table", None)
    if table is not None:
        return str(getattr(table, "name", table))
    return "?"


def _columns_of(obj: Any) -> tuple[str, ...]:
    """Ordered column names behind an Index / UniqueConstraint.

    Expression indexes (``lower(email)``) have no plain columns; fall back
    to the rendered expression so they still get a stable identity.
    """
    cols = [str(getattr(c, "name", c)) for c in getattr(obj, "columns", []) or []]
    if cols:
        return tuple(cols)
    expressions = getattr(obj, "expressions", None) or []
    return tuple(str(e) for e in expressions)


def _shape_signature(diff: Any) -> tuple[Any, ...] | None:
    """Name-independent identity of an index / unique-constraint diff.

    Alembic reports a *renamed* index as a remove + an add, and reports the
    same uniqueness guarantee spelled as a UniqueConstraint on one side and
    a unique Index on the other the same way. Both are cosmetic: the
    database enforces exactly the same thing. Reducing each to
    ``(table, columns, unique)`` lets those pairs cancel out, so the guard
    keeps its signal for real structural drift.
    """
    op = diff[0]
    if op not in (
        "add_index",
        "remove_index",
        "add_constraint",
        "remove_constraint",
    ):
        return None
    obj = diff[1]
    columns = _columns_of(obj)
    if not columns:
        return None
    if op.endswith("constraint"):
        # Only uniqueness constraints have an index equivalent; leave check
        # and foreign-key constraints to be reported normally.
        if not isinstance(obj, sa.UniqueConstraint):
            return None
        unique = True
    else:
        unique = bool(getattr(obj, "unique", False))
    return (_table_of(obj), columns, unique, _partial_predicate(obj))


def _partial_predicate(obj: Any) -> str | None:
    """WHERE clause of a partial index, normalised to a string.

    Part of the signature: a full index and a partial one over the same
    columns are different objects, and collapsing them would hide a real
    difference (HRP-540 review).
    """
    options = getattr(obj, "dialect_options", None)
    if options is None or "postgresql" not in options:
        return None
    where = options["postgresql"].get("where")
    return None if where is None else str(where)


def _reconcile_naming(diffs: list[Any]) -> list[Any]:
    """Drop add/remove pairs that differ only in name or DDL spelling."""
    added: dict[tuple[Any, ...], list[Any]] = {}
    removed: dict[tuple[Any, ...], list[Any]] = {}
    for diff in diffs:
        signature = _shape_signature(diff)
        if signature is None:
            continue
        bucket = added if diff[0].startswith("add_") else removed
        bucket.setdefault(signature, []).append(diff)

    cancelled: set[int] = set()
    for signature, add_list in added.items():
        remove_list = removed.get(signature, [])
        for add_diff, remove_diff in zip(add_list, remove_list, strict=False):
            cancelled.add(id(add_diff))
            cancelled.add(id(remove_diff))

    return [d for d in diffs if id(d) not in cancelled]


def _diff_key(diff: Any) -> str:
    """Collapse an alembic diff tuple into a stable, greppable identity.

    ``compare_metadata`` yields either a tuple whose first element is the
    operation name, or a list of such tuples (grouped column changes).
    """
    op = diff[0]

    if op in ("add_table", "remove_table"):
        return f"{op}:{diff[1].name}"

    if op in ("add_column", "remove_column"):
        # (op, schema, table_name, Column)
        return f"{op}:{diff[2]}.{diff[3].name}"

    if op in ("add_index", "remove_index"):
        index = diff[1]
        return f"{op}:{_table_of(index)}.{index.name}"

    if op in ("add_constraint", "remove_constraint"):
        constraint = diff[1]
        # Constraints declared inline on a model carry no explicit name.
        label = constraint.name or "+".join(_columns_of(constraint)) or "?"
        return f"{op}:{_table_of(constraint)}.{label}"

    if op.startswith("modify_"):
        # (op, schema, table_name, column_name, {...}, old, new)
        # The two values are part of the identity: allowlisting
        # "interviews.file_size_bytes is BIGINT in the DB" must not also
        # excuse it silently becoming SMALLINT tomorrow.
        return f"{op}:{diff[2]}.{diff[3]}:db={diff[-2]!r}:model={diff[-1]!r}"

    return f"{op}:{diff[1:]}"


def _describe(diff: Any) -> str:
    """Human-readable one-liner for a failure message."""
    op = diff[0]
    key = _diff_key(diff)
    if op.startswith("modify_"):
        return f"{key}: db={diff[-2]!r} model={diff[-1]!r}"
    return key


def _key_table(key: str) -> str:
    """Table an ``ALLOWED_DRIFT`` key refers to."""
    target = key.split(":", 1)[1]
    return target.split(".", 1)[0]


def _flatten(diffs: list[Any]) -> list[Any]:
    flat: list[Any] = []
    for diff in diffs:
        if isinstance(diff, list):
            flat.extend(diff)
        else:
            flat.append(diff)
    return flat


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _alembic_config(target_url: str) -> Config:
    cfg = Config()
    # alembic.ini paths are relative to backend/; resolve them so the test
    # does not depend on pytest's working directory.
    versions = BACKEND_DIR / "migrations" / "versions"
    locations = [versions]
    # migrations/versions/ee is enterprise-only and absent from a community
    # checkout — alembic rejects a version_location that does not exist.
    if (versions / "ee").is_dir():
        locations.append(versions / "ee")
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    # os.pathsep, not a space: a checkout under a path with a space in it
    # would otherwise split into bogus version locations.
    cfg.set_main_option(
        "version_locations", os.pathsep.join(str(path) for path in locations)
    )
    cfg.set_main_option("path_separator", "os")
    cfg.set_main_option("sqlalchemy.url", target_url)
    return cfg


@pytest.fixture(scope="module")
def migrated_engine():
    """A database built purely by ``alembic upgrade heads``."""
    admin_url = _sync(_server_url("postgres"))
    target_async_url = _server_url(MIGRATIONS_DB_NAME)
    target_sync_url = _sync(target_async_url)

    def _drop(conn: sa.Connection) -> None:
        conn.execute(
            sa.text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = :name AND pid <> pg_backend_pid()"
            ),
            {"name": MIGRATIONS_DB_NAME},
        )
        conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{MIGRATIONS_DB_NAME}"'))

    admin = sa.create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            _drop(conn)
            conn.execute(sa.text(f'CREATE DATABASE "{MIGRATIONS_DB_NAME}"'))
    finally:
        admin.dispose()

    engine = sa.create_engine(target_sync_url)
    with engine.begin() as conn:
        # app/modules/ai/models.py uses pgvector's Vector type.
        conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))

    # migrations/env.py reads app.config.settings.database_url at call time
    # and drives its own asyncio loop, so point the setting at the throwaway
    # database and run the upgrade from this (sync) test function.
    previous_url = settings.database_url
    previous_env = os.environ.get("DATABASE_URL")
    settings.database_url = target_async_url
    os.environ["DATABASE_URL"] = target_async_url
    try:
        command.upgrade(_alembic_config(target_sync_url), "heads")
    finally:
        settings.database_url = previous_url
        if previous_env is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_env

    yield engine

    engine.dispose()

    # The name is per-process now, so leaving it behind would litter the
    # server with one scratch database per run.
    admin = sa.create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            _drop(conn)
    finally:
        admin.dispose()


@pytest.fixture(scope="module")
def full_metadata() -> sa.MetaData:
    """``Base.metadata`` populated exactly like migrations/env.py does.

    Enterprise models register themselves through the module-level soft
    import above; in a community checkout they are simply absent.
    """
    import_all_models()
    return Base.metadata


# ---------------------------------------------------------------------------
# The guard
# ---------------------------------------------------------------------------


def test_models_match_migrations(migrated_engine, full_metadata) -> None:
    """Models and migrations describe the same schema.

    Fails with the exact diff when a model is changed without a migration
    (or a migration lands without the model change).
    """
    with migrated_engine.connect() as conn:
        context = MigrationContext.configure(conn, opts={"compare_type": True})
        diffs = _reconcile_naming(_flatten(compare_metadata(context, full_metadata)))

    unexpected = [d for d in diffs if _diff_key(d) not in ALLOWED_DRIFT]

    assert not unexpected, (
        "Schema drift between SQLAlchemy models and Alembic migrations.\n\n"
        + "\n".join(f"  - {_describe(d)}" for d in unexpected)
        + "\n\nEither add the missing Alembic migration, or — if the "
        "difference is deliberate and safe — add its key to ALLOWED_DRIFT "
        "in this file with a reason."
    )


def test_allowlist_has_no_stale_entries(migrated_engine, full_metadata) -> None:
    """Every ``ALLOWED_DRIFT`` entry still corresponds to real drift.

    Keeps the allowlist from rotting into a list of differences somebody
    already fixed — a stale entry would silently tolerate that drift if it
    ever came back.

    Entries for tables the checkout does not have are ignored rather than
    reported: a community build has no enterprise tables, and its copy of
    this file is the same one.
    """
    with migrated_engine.connect() as conn:
        context = MigrationContext.configure(conn, opts={"compare_type": True})
        diffs = _reconcile_naming(_flatten(compare_metadata(context, full_metadata)))
        present = set(sa.inspect(conn).get_table_names())

    observed = {_diff_key(d) for d in diffs}
    stale = sorted(
        key for key in set(ALLOWED_DRIFT) - observed if _key_table(key) in present
    )

    assert not stale, (
        "ALLOWED_DRIFT lists differences that no longer exist — remove them:\n"
        + "\n".join(f"  - {key}" for key in stale)
    )


def test_guard_detects_unmigrated_model(migrated_engine) -> None:
    """The guard actually fires — a model with no migration is reported.

    Without this, a silent failure in the comparison (wrong metadata, an
    over-eager reconciliation) would make ``test_models_match_migrations``
    pass vacuously forever, which is the exact failure mode HRP-540 exists
    to prevent.
    """
    unmigrated = sa.MetaData()
    sa.Table(
        "hrp540_guard_probe",
        unmigrated,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("payload", sa.String(32), nullable=False),
    )

    with migrated_engine.connect() as conn:
        context = MigrationContext.configure(conn, opts={"compare_type": True})
        diffs = _reconcile_naming(_flatten(compare_metadata(context, unmigrated)))

    keys = {_diff_key(d) for d in diffs}
    assert "add_table:hrp540_guard_probe" in keys
    assert "add_table:hrp540_guard_probe" not in ALLOWED_DRIFT
