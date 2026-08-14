#!/usr/bin/env bash
# Nightly ingestion pipeline for production, runs inside the `api` Docker container.
# Schedule with cron: 0 2 * * * /path/to/scripts/nightly_ingest.sh >> /path/to/log/nightly.log 2>&1

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
COMPOSE=(docker compose -f "$PROJECT_DIR/docker-compose.prod.yml")

cd "$PROJECT_DIR"

echo "[$(date -Iseconds)] Starting nightly ingest"
"${COMPOSE[@]}" exec -T api python manage.py bootstrap_wells
"${COMPOSE[@]}" exec -T api python manage.py fetch_measurements
echo "[$(date -Iseconds)] Nightly ingest complete"
