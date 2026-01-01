#!/usr/bin/env bash
set -euo pipefail

# PostgreSQL restore for YasarGold.
# Usage:
#   export DATABASE_URL='postgresql://user:pass@host:5432/dbname'
#   CONFIRM_RESTORE=YES BACKUP_FILE=/path/to/yasargold_pg_....dump ./restore_postgres.sh
#
# WARNING:
# - This will overwrite existing data in the target database (uses --clean --if-exists).
# - Best practice is to restore into a NEW database first and then switch.

if [[ "${CONFIRM_RESTORE:-}" != "YES" ]]; then
  echo "ERROR: set CONFIRM_RESTORE=YES to proceed" >&2
  exit 1
fi

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "ERROR: DATABASE_URL is not set" >&2
  exit 1
fi

if [[ -z "${BACKUP_FILE:-}" ]]; then
  echo "ERROR: BACKUP_FILE is not set" >&2
  exit 1
fi

if [[ ! -f "$BACKUP_FILE" ]]; then
  echo "ERROR: backup file not found: $BACKUP_FILE" >&2
  exit 1
fi

if ! command -v pg_restore >/dev/null 2>&1; then
  echo "ERROR: pg_restore not found. Install PostgreSQL client tools on the server." >&2
  exit 1
fi

echo "Restoring: $BACKUP_FILE"

pg_restore \
  --clean \
  --if-exists \
  --no-owner \
  --no-acl \
  --dbname "$DATABASE_URL" \
  "$BACKUP_FILE"

echo "OK: restore completed. Run migrations next: alembic upgrade head"
