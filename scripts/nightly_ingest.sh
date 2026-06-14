#!/usr/bin/env bash
# Nightly ingestion pipeline.
# Schedule with cron: 0 2 * * * /path/to/scripts/nightly_ingest.sh >> /var/log/opengrondwaterkaart/nightly.log 2>&1
# Monthly baselines: 0 3 1 * * /path/to/scripts/monthly_baselines.sh >> /var/log/opengrondwaterkaart/baselines.log 2>&1

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

source "$PROJECT_DIR/env/bin/activate"

cd "$PROJECT_DIR"

echo "[$(date -Iseconds)] Starting nightly ingest"
python manage.py bootstrap_wells
python manage.py fetch_measurements
python manage.py refresh_status
python manage.py purge_old_measurements
echo "[$(date -Iseconds)] Nightly ingest complete"
