#!/usr/bin/env bash
set -euo pipefail

# HRPulsar database backup script
# Usage: ./scripts/backup_db.sh [output_dir]
#
# Cron example (daily at 3am):
#   0 3 * * * /opt/hrpulsar/scripts/backup_db.sh /opt/hrpulsar/backups

OUTPUT_DIR="${1:-./backups}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
FILENAME="hrpulsar_${TIMESTAMP}.sql.gz"

# Self-hosted stacks run from docker-compose.self-hosted.yml; fall back to
# the default compose file for other setups.
if [ -z "${COMPOSE_FILE:-}" ] && [ -f docker-compose.self-hosted.yml ]; then
    export COMPOSE_FILE=docker-compose.self-hosted.yml
fi

mkdir -p "$OUTPUT_DIR"

echo "Starting backup..."
docker compose exec -T postgres pg_dump -U hrpulsar hrpulsar | gzip > "${OUTPUT_DIR}/${FILENAME}"

echo "Backup saved: ${OUTPUT_DIR}/${FILENAME}"

# Cleanup: keep last 7 days
find "$OUTPUT_DIR" -name "hrpulsar_*.sql.gz" -mtime +7 -delete
echo "Old backups cleaned up (7-day retention)."
