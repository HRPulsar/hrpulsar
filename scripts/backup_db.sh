#!/usr/bin/env bash
set -Eeuo pipefail

# HRPulsar backup script — Postgres dump plus the MinIO file-storage volume
# (resumes, interview recordings, generated reports).
# Usage: ./scripts/backup_db.sh [output_dir]
#
# Installed as a daily cron job by scripts/server-setup.sh
# (/etc/cron.d/hrpulsar-backup, 3:00 server time).
#
# Optional settings, read from the stack's .env next to the compose file:
#   S3_ENDPOINT / S3_ACCESS_KEY / S3_SECRET_KEY / S3_BUCKET
#       off-site copy of every dump (S3-compatible, e.g. Cloudflare R2)
#   BACKUP_S3_PREFIX      key prefix for that copy (default: backups)
#   SLACK_BOT_TOKEN + BACKUP_SLACK_CHANNEL
#       Slack alert when a backup fails — without it a broken backup is silent

OUTPUT_DIR="${1:-./backups}"
ENV_FILE="${ENV_FILE:-.env}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"
# A dump of an empty or half-written database is worse than no dump: it looks
# like a backup. Real dumps are megabytes even for a fresh install.
MIN_BYTES="${MIN_BYTES:-10240}"

# .env holds unquoted values with spaces and angle brackets ("HRPulsar
# <noreply@...>"), so it cannot be sourced.
env_get() {
    [ -f "$ENV_FILE" ] || return 0
    sed -n "s/^$1=//p" "$ENV_FILE" | head -1
}

fail() {
    echo "Backup FAILED: $1" >&2
    local token channel
    token=$(env_get SLACK_BOT_TOKEN)
    channel=$(env_get BACKUP_SLACK_CHANNEL)
    if [ -n "$token" ] && [ -n "$channel" ]; then
        curl -sS -X POST https://slack.com/api/chat.postMessage \
            -H "Authorization: Bearer $token" \
            -H 'Content-type: application/json; charset=utf-8' \
            --data "$(printf '{"channel":"%s","text":"HRPulsar backup FAILED on %s: %s"}' \
                "$channel" "$(hostname)" "$1")" >/dev/null || true
    fi
    exit 1
}
trap 'fail "unexpected error at line $LINENO"' ERR

# Self-hosted stacks run from docker-compose.self-hosted.yml; fall back to
# the default compose file for other setups.
if [ -z "${COMPOSE_FILE:-}" ] && [ -f docker-compose.self-hosted.yml ]; then
    export COMPOSE_FILE=docker-compose.self-hosted.yml
fi

mkdir -p "$OUTPUT_DIR"
STAMP=$(date +%Y%m%d_%H%M%S)
FILE="${OUTPUT_DIR}/hrpulsar_${STAMP}.sql.gz"

# Off-site copy: a backup on the same disk as the database is not a backup.
# Point the S3_* values at a provider OTHER than the bundled MinIO — copying
# the file storage into itself is not an off-site copy.
offsite_copy() {
    local path="$1"
    local endpoint bucket key secret prefix code
    endpoint=$(env_get S3_ENDPOINT)
    bucket=$(env_get S3_BUCKET)
    key=$(env_get S3_ACCESS_KEY)
    secret=$(env_get S3_SECRET_KEY)
    [ -n "$endpoint" ] && [ -n "$bucket" ] && [ -n "$key" ] || return 0
    prefix=$(env_get BACKUP_S3_PREFIX)
    prefix="${prefix:-backups}"
    code=$(curl -sS -o /dev/null -w '%{http_code}' \
        --aws-sigv4 "aws:amz:auto:s3" --user "${key}:${secret}" \
        -T "$path" "${endpoint}/${bucket}/${prefix}/$(basename "$path")") \
        || fail "off-site upload errored"
    [ "$code" = "200" ] || fail "off-site upload returned HTTP ${code}"
    echo "Off-site copy: ${bucket}/${prefix}/$(basename "$path")"
}

echo "Starting backup..."
# --clean --if-exists --no-owner: a restore has to be able to pour into a
# live database. Without them psql walks through a wall of "already exists"
# and leaves a half-old, half-new schema behind; --no-owner drops the
# GRANT/OWNER statements that fail when restoring under another role.
docker compose exec -T postgres pg_dump -U hrpulsar --clean --if-exists --no-owner hrpulsar \
    | gzip > "$FILE" || fail "pg_dump failed"

SIZE=$(wc -c < "$FILE")
[ "$SIZE" -ge "$MIN_BYTES" ] || fail "dump is only ${SIZE} bytes (expected >= ${MIN_BYTES})"
echo "Backup saved: ${FILE} (${SIZE} bytes)"
offsite_copy "$FILE"

# File storage: resumes, interview recordings and generated reports live in
# the MinIO volume, not in Postgres — a database-only backup restores an
# instance where every attachment 404s. `docker cp <container>:/data -`
# streams the volume out as a tar, so this needs no helper image and no
# volume name. Skipped when storage is external (no minio container).
MINIO_CID=$(docker compose ps -q minio 2>/dev/null || true)
if [ -n "$MINIO_CID" ]; then
    MINIO_FILE="${OUTPUT_DIR}/minio_${STAMP}.tar.gz"
    docker cp "$MINIO_CID:/data" - | gzip > "$MINIO_FILE" || fail "MinIO backup failed"
    [ -s "$MINIO_FILE" ] || fail "MinIO archive is empty"
    echo "File storage saved: ${MINIO_FILE} ($(wc -c < "$MINIO_FILE") bytes)"
    offsite_copy "$MINIO_FILE"
else
    echo "No MinIO container in this stack — external file storage, skipping."
fi

# Cleanup: local retention only, the off-site copies are kept by bucket policy
find "$OUTPUT_DIR" \( -name 'hrpulsar_*.sql.gz' -o -name 'minio_*.tar.gz' \) \
    -mtime +"$RETENTION_DAYS" -delete
echo "Old local backups cleaned up (${RETENTION_DAYS}-day retention)."
