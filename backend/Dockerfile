# Build context is the repo root (see docker-compose.self-hosted.yml and the
# deploy workflows) so that version.py — the single source of the app version —
# ships inside the image.
FROM python:3.14-slim

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev postgresql-client curl && \
    rm -rf /var/lib/apt/lists/*

# Non-root user
RUN groupadd -r appgroup && useradd -r -g appgroup -d /app -s /sbin/nologin appuser

WORKDIR /app

# Install Python dependencies from the pip-compile lock (HRP-398) —
# reproducible builds; regenerate with `make lock`
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY backend/app/ app/
COPY backend/migrations/ migrations/
COPY backend/alembic.ini .
COPY backend/server.py .
COPY backend/entrypoint.sh .
COPY version.py .
RUN chmod +x entrypoint.sh

# Copy enterprise module if present (will be empty in community edition)
COPY backend/ee* ee/

# Install enterprise-only dependencies when the ee/ lock is shipped.
# Community builds carry no ee/ directory, so the file is absent — the
# `[ -f ... ]` guard makes the layer a no-op there. The unpinned .in
# fallback covers enterprise overlays predating the lock.
RUN if [ -f ee/requirements.txt ]; then \
        pip install --no-cache-dir -r ee/requirements.txt; \
    elif [ -f ee/requirements.in ]; then \
        pip install --no-cache-dir -r ee/requirements.in; \
    fi

RUN chown -R appuser:appgroup /app

USER appuser

# Optional override; when empty the app reads the version from version.py.
ARG APP_VERSION=
ENV APP_VERSION=${APP_VERSION} \
    PYTHONPATH=/app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["./entrypoint.sh"]
