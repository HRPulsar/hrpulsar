#!/bin/bash
set -e

echo "HRPulsar Backend — starting..."

# Wait for PostgreSQL
echo "Waiting for PostgreSQL..."
until pg_isready -h "${DB_HOST:-postgres}" -p "${DB_PORT:-5432}" -U "${DB_USER:-hrpulsar}" -q 2>/dev/null; do
    sleep 1
done
echo "PostgreSQL is ready."

# Check enterprise module availability
if [ -d "/app/ee" ] && [ -f "/app/ee/__init__.py" ]; then
    echo "Enterprise module: found"
else
    echo "Enterprise module: not found"
fi

# Determine run mode from first argument
MODE="${1:-api}"

case "$MODE" in
    api)
        # Run migrations unless managed by deploy script
        if [ "${SKIP_MIGRATIONS:-false}" = "true" ]; then
            echo "Skipping migrations (managed by deploy script)."
        else
            echo "Running database migrations..."
            alembic upgrade heads
            echo "Migrations complete."
        fi

        # Prometheus multiprocess mode: shared dir for metrics across workers
        export PROMETHEUS_MULTIPROC_DIR=$(mktemp -d)

        # Start server via Python launcher so we can pass ws_ping_interval=None
        # (the CLI flag is float-typed and cannot disable keepalive).
        echo "Starting uvicorn..."
        exec python server.py
        ;;
    migrate)
        echo "Running database migrations..."
        alembic upgrade heads
        echo "Migrations complete."
        ;;
    worker)
        echo "Starting Celery worker..."
        exec celery -A app.core.celery_app:celery worker \
            --loglevel="${LOG_LEVEL:-info}" \
            --concurrency="${CELERY_CONCURRENCY:-2}"
        ;;
    beat)
        echo "Starting Celery Beat scheduler..."
        exec celery -A app.core.celery_app:celery beat \
            --loglevel="${LOG_LEVEL:-info}"
        ;;
    *)
        echo "Unknown mode: $MODE (use api, migrate, worker, or beat)"
        exit 1
        ;;
esac
