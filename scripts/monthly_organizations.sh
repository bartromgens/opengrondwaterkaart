#!/usr/bin/env bash
# Monthly sync of well owner/bronhouder organization names, runs inside the `api` Docker container.
# Schedule with cron: 0 4 1 * * /path/to/scripts/monthly_organizations.sh >> /path/to/log/organizations.log 2>&1

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
COMPOSE=(docker compose -f "$PROJECT_DIR/docker-compose.prod.yml")

cd "$PROJECT_DIR"

echo "[$(date -Iseconds)] Starting monthly organizations sync"
"${COMPOSE[@]}" exec -T api python manage.py sync_bro_organizations
echo "[$(date -Iseconds)] Organizations sync complete"
