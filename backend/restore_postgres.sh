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

if ! command -v psql >/dev/null 2>&1; then
  echo "ERROR: psql not found. Install PostgreSQL client tools on the server." >&2
  exit 1
fi

echo "Restoring: $BACKUP_FILE"

psql \
  --dbname "$DATABASE_URL" \
  -v ON_ERROR_STOP=1 \
  -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = current_database() AND pid <> pg_backend_pid();"

set +e
RESTORE_STDERR_FILE="$(mktemp -t yasargold_pg_restore_stderr.XXXXXX)"
pg_restore \
  --clean \
  --if-exists \
  --no-owner \
  --no-acl \
  --dbname "$DATABASE_URL" \
  "$BACKUP_FILE" 2>"$RESTORE_STDERR_FILE"
RESTORE_EXIT=$?
set -e

if [[ "$RESTORE_EXIT" -ne 0 ]]; then
  if grep -Eqi 'text format dump|please use psql' "$RESTORE_STDERR_FILE"; then
    echo "Detected plain SQL dump. Falling back to psql..."
    psql \
      --dbname "$DATABASE_URL" \
      -v ON_ERROR_STOP=1 \
      -f "$BACKUP_FILE"
  else
    cat "$RESTORE_STDERR_FILE" >&2 || true
    rm -f "$RESTORE_STDERR_FILE"
    exit "$RESTORE_EXIT"
  fi
fi

rm -f "$RESTORE_STDERR_FILE"

echo "OK: restore completed. Run migrations next: alembic upgrade head"
