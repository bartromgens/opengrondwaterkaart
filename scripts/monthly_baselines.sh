#!/usr/bin/env bash
# Monthly baseline recomputation for production, runs inside the `api` Docker container.
# Schedule with cron: 0 3 1 * * /path/to/scripts/monthly_baselines.sh >> /path/to/log/baselines.log 2>&1

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
COMPOSE=(docker compose -f "$PROJECT_DIR/docker-compose.prod.yml")

cd "$PROJECT_DIR"

echo "[$(date -Iseconds)] Starting monthly baseline computation"
"${COMPOSE[@]}" exec -T api python manage.py compute_baselines --period-type week
echo "[$(date -Iseconds)] Baseline computation complete"
