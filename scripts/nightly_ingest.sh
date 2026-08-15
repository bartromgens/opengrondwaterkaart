#!/usr/bin/env bash
# Nightly ingestion pipeline for production, runs inside the `api` Docker container.
# Schedule with cron: 0 2 * * * /path/to/scripts/nightly_ingest.sh >> /path/to/log/nightly.log 2>&1
# Overlapping cron invocations are skipped via flock; fetch_measurements also
# refuses a second start if a previous run is still in progress.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
COMPOSE=(docker compose -f "$PROJECT_DIR/docker-compose.prod.yml")
LOCK_FILE="$PROJECT_DIR/log/nightly_ingest.lock"

cd "$PROJECT_DIR"

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "[$(date -Iseconds)] Nightly ingest already running, skipping"
  exit 0
fi

echo "[$(date -Iseconds)] Starting nightly ingest"
"${COMPOSE[@]}" exec -T api python manage.py bootstrap_wells
"${COMPOSE[@]}" exec -T api python manage.py fetch_measurements
echo "[$(date -Iseconds)] Nightly ingest complete"
