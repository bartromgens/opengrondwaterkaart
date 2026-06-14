#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

source "$PROJECT_DIR/env/bin/activate"

cd "$PROJECT_DIR"

echo "[$(date -Iseconds)] Starting monthly baseline computation"
python manage.py compute_baselines --period-type week
echo "[$(date -Iseconds)] Baseline computation complete"
