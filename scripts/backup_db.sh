#!/usr/bin/env bash
set -Eeuo pipefail

# HRPulsar database backup script
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
FILE="${OUTPUT_DIR}/hrpulsar_$(date +%Y%m%d_%H%M%S).sql.gz"

echo "Starting backup..."
docker compose exec -T postgres pg_dump -U hrpulsar hrpulsar | gzip > "$FILE" \
    || fail "pg_dump failed"

SIZE=$(wc -c < "$FILE")
[ "$SIZE" -ge "$MIN_BYTES" ] || fail "dump is only ${SIZE} bytes (expected >= ${MIN_BYTES})"
echo "Backup saved: ${FILE} (${SIZE} bytes)"

# Off-site copy: a backup on the same disk as the database is not a backup.
S3_ENDPOINT_V=$(env_get S3_ENDPOINT)
S3_BUCKET_V=$(env_get S3_BUCKET)
S3_KEY_V=$(env_get S3_ACCESS_KEY)
S3_SECRET_V=$(env_get S3_SECRET_KEY)
if [ -n "$S3_ENDPOINT_V" ] && [ -n "$S3_BUCKET_V" ] && [ -n "$S3_KEY_V" ]; then
    PREFIX=$(env_get BACKUP_S3_PREFIX)
    PREFIX="${PREFIX:-backups}"
    CODE=$(curl -sS -o /dev/null -w '%{http_code}' \
        --aws-sigv4 "aws:amz:auto:s3" --user "${S3_KEY_V}:${S3_SECRET_V}" \
        -T "$FILE" "${S3_ENDPOINT_V}/${S3_BUCKET_V}/${PREFIX}/$(basename "$FILE")") \
        || fail "off-site upload errored"
    [ "$CODE" = "200" ] || fail "off-site upload returned HTTP ${CODE}"
    echo "Off-site copy: ${S3_BUCKET_V}/${PREFIX}/$(basename "$FILE")"
fi

# Cleanup: local retention only, the off-site copies are kept by bucket policy
find "$OUTPUT_DIR" -name 'hrpulsar_*.sql.gz' -mtime +"$RETENTION_DAYS" -delete
echo "Old local backups cleaned up (${RETENTION_DAYS}-day retention)."
