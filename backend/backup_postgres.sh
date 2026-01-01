#!/usr/bin/env bash
set -euo pipefail

# PostgreSQL backup for YasarGold.
# Usage:
#   export DATABASE_URL='postgresql://user:pass@host:5432/dbname'
#   ./backup_postgres.sh
#
# Notes:
# - Prefer using .pgpass or secret manager instead of embedding password in DATABASE_URL.
# - Produces pg_dump custom-format file (.dump) which is compressed and supports parallel restore.

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "ERROR: DATABASE_URL is not set" >&2
  exit 1
fi

if ! [[ "${DATABASE_URL}" =~ ^postgres(ql)?:// ]]; then
  echo "ERROR: DATABASE_URL does not look like PostgreSQL (got: ${DATABASE_URL})" >&2
  exit 1
fi

BACKUP_DIR="${BACKUP_DIR:-"$(cd "$(dirname "$0")" && pwd)/../backups/postgres"}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

umask 077
mkdir -p "$BACKUP_DIR"

TS="$(date -u +"%Y%m%dT%H%M%SZ")"
OUT_FILE="$BACKUP_DIR/yasargold_pg_${TS}.dump"

if ! command -v pg_dump >/dev/null 2>&1; then
  echo "ERROR: pg_dump not found. Install PostgreSQL client tools on the server." >&2
  exit 1
fi

# -Fc: custom format (compressed)
# --no-owner/--no-acl: avoids ownership/permission issues across environments
pg_dump \
  --format=custom \
  --no-owner \
  --no-acl \
  --dbname "$DATABASE_URL" \
  --file "$OUT_FILE"

echo "OK: created backup: $OUT_FILE"

# Retention cleanup
if [[ "$RETENTION_DAYS" =~ ^[0-9]+$ ]] && [[ "$RETENTION_DAYS" -gt 0 ]]; then
  find "$BACKUP_DIR" -type f -name 'yasargold_pg_*.dump' -mtime "+$RETENTION_DAYS" -print -delete || true
fi
