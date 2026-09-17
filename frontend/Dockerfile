# Stage 1: Build
FROM node:22-alpine AS builder

WORKDIR /app

# Optional override; when empty next.config.ts falls back to /version.py
# (copied below) — the repo-root source of truth for the app version.
ARG APP_VERSION=
ENV APP_VERSION=${APP_VERSION}

# Sentry source-map upload (M31). Builder stage only, so the token never
# reaches the runner image. All three empty (the default) = next.config.ts
# skips withSentryConfig and the build is exactly what it is today.
ARG SENTRY_AUTH_TOKEN=
ARG SENTRY_ORG=
ARG SENTRY_PROJECT=
ENV SENTRY_AUTH_TOKEN=${SENTRY_AUTH_TOKEN} \
    SENTRY_ORG=${SENTRY_ORG} \
    SENTRY_PROJECT=${SENTRY_PROJECT}

COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci

COPY frontend/ .

# version.py lands at /version.py = ../version.py from /app, where the
# next.config.ts fallback expects it when no APP_VERSION build-arg is given
COPY version.py /version.py

RUN npm run build

# Stage 2: Production
FROM node:22-alpine AS runner

WORKDIR /app

RUN addgroup --system --gid 1001 appgroup && \
    adduser --system --uid 1001 appuser

# Copy built output (chown so ISR can write back into .next/ at runtime)
COPY --from=builder --chown=appuser:appgroup /app/.next/standalone ./
COPY --from=builder --chown=appuser:appgroup /app/.next/static ./.next/static
COPY --from=builder --chown=appuser:appgroup /app/public ./public

USER appuser

ARG APP_VERSION=
ENV APP_VERSION=${APP_VERSION}

# So `docker image inspect` on a host answers "which release is this?" —
# a :latest tag alone cannot (HRP review M28).
LABEL org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.source="https://github.com/HRPulsar/hrpulsar"

ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

EXPOSE 3000

# 127.0.0.1, not localhost: busybox wget resolves localhost to ::1 while the
# Next.js standalone server listens on IPv4 only.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:3000/ || exit 1

CMD ["node", "server.js"]
