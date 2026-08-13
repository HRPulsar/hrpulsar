import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

# Add backend/ to sys.path so 'app' is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from alembic import context
from app.config import settings
from app.database import Base, import_all_models, make_async_engine

# Import all models so Base.metadata picks them up
import_all_models()

# Import EE models if available (enterprise edition only)
try:  # noqa: SIM105
    from ee.models import (  # noqa: F401
        AuditLog,
        BlogPost,
        CreditReservation,
        CreditTransaction,
        QuizCompletionEvent,
        TenantCredits,
    )
except ImportError:
    pass

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    # lock_timeout="10s" — DDL fails fast if a long-running session holds a
    # lock on the target table, instead of queuing for AccessExclusive and
    # blocking every new reader behind us (added after a 2026-04 lock pile-up).
    connectable = make_async_engine(settings.database_url, lock_timeout="10s")
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
