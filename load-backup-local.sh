#!/usr/bin/env bash
set -euo pipefail

DB_HOST="localhost"
DB_PORT="5436"
DB_USER="opengrondwaterkaart"
DB_NAME="opengrondwaterkaart"
DB_PASSWORD="opengrondwaterkaart"
BACKUP_DIR="./backups"
POSTGIS_IMAGE="postgis/postgis:17-3.5"

usage() {
  echo "Usage: $0 [--yes] [dump-file]"
  echo "  Load a production backup into the local dev database."
  echo "  Default dump file: newest file in ${BACKUP_DIR}/"
  exit 1
}

YES=false
DUMP_FILE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes | -y)
      YES=true
      shift
      ;;
    -h | --help)
      usage
      ;;
    *)
      if [[ -n "$DUMP_FILE" ]]; then
        usage
      fi
      DUMP_FILE="$1"
      shift
      ;;
  esac
done

if [[ -z "$DUMP_FILE" ]]; then
  DUMP_FILE="$(ls -t "${BACKUP_DIR}"/opengrondwaterkaart_*.dump 2>/dev/null | head -1 || true)"
fi

if [[ -z "$DUMP_FILE" || ! -f "$DUMP_FILE" ]]; then
  echo "Error: No dump file found. Run ./backup-db.sh first or pass a dump path."
  exit 1
fi

if ! head -c 5 "$DUMP_FILE" | grep -q PGDMP; then
  echo "Error: ${DUMP_FILE} is not a PostgreSQL custom-format dump."
  exit 1
fi

if ! command -v docker >/dev/null; then
  echo "Error: docker not found. Production dumps require PostgreSQL 17 pg_restore (via Docker)."
  exit 1
fi

if ! docker run --rm --network host "${POSTGIS_IMAGE}" \
  pg_isready -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1; then
  echo "Error: Cannot reach ${DB_USER}@${DB_HOST}:${DB_PORT}/${DB_NAME}."
  echo "Start the local database first: docker compose up -d db"
  exit 1
fi

DUMP_PATH="$(realpath "$DUMP_FILE")"

echo "Dump file:  ${DUMP_FILE} ($(du -h "$DUMP_FILE" | cut -f1))"
echo "Target DB:  ${DB_USER}@${DB_HOST}:${DB_PORT}/${DB_NAME}"

if [[ "$YES" != true ]]; then
  read -r -p "This will overwrite the local dev database. Continue? [y/N] " reply
  if [[ ! "$reply" =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 1
  fi
fi

export PGPASSWORD="$DB_PASSWORD"

docker run --rm \
  --network host \
  -e PGPASSWORD="$DB_PASSWORD" \
  -v "${DUMP_PATH}:/dump.dump:ro" \
  "${POSTGIS_IMAGE}" \
  pg_restore \
  --host="$DB_HOST" \
  --port="$DB_PORT" \
  --username="$DB_USER" \
  --dbname="$DB_NAME" \
  --clean \
  --if-exists \
  --no-owner \
  --no-acl \
  /dump.dump

echo "Local dev database loaded from ${DUMP_FILE}"
