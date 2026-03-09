#!/usr/bin/env bash
set -euo pipefail

# Safe PostgreSQL restore drill for YasarGold.
#
# Purpose:
# - Verify that a backup file can be restored successfully WITHOUT touching the
#   production database.
# - Restore into a temporary database on the same PostgreSQL server.
#
# Usage:
#   export DATABASE_URL='postgresql://user:pass@host:5432/yasargold'
#   CONFIRM_DRY_RUN=YES BACKUP_FILE=/path/to/yasargold_pg_....dump \
#     ./backend/verify_postgres_restore_dry_run.sh
#
# Optional env vars:
#   TEST_DB_NAME=yasargold_test
#   KEEP_TEST_DB=1           # default: 1 (keep DB for inspection)
#   DROP_IF_EXISTS=1         # default: 1
#   PLAIN_SQL_FALLBACK=1     # default: 1

if [[ "${CONFIRM_DRY_RUN:-}" != "YES" ]]; then
  echo "ERROR: set CONFIRM_DRY_RUN=YES to proceed" >&2
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

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 not found" >&2
  exit 1
fi

for tool in psql pg_restore; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "ERROR: $tool not found. Install PostgreSQL client tools on the server." >&2
    exit 1
  fi
done

TEST_DB_NAME="${TEST_DB_NAME:-yasargold_test}"
KEEP_TEST_DB="${KEEP_TEST_DB:-1}"
DROP_IF_EXISTS="${DROP_IF_EXISTS:-1}"
PLAIN_SQL_FALLBACK="${PLAIN_SQL_FALLBACK:-1}"

mapfile -t URLS < <(python3 - <<'PY'
import os
from urllib.parse import urlsplit, urlunsplit
url = os.environ['DATABASE_URL']
parts = urlsplit(url)
path = parts.path or ''
if not path.startswith('/') or len(path) <= 1:
    raise SystemExit('DATABASE_URL must include a database name in the path')
orig_db = path[1:]
target_db = os.environ.get('TEST_DB_NAME', 'yasargold_test')
maint_db = 'postgres'
print(urlunsplit((parts.scheme, parts.netloc, '/' + maint_db, parts.query, parts.fragment)))
print(urlunsplit((parts.scheme, parts.netloc, '/' + target_db, parts.query, parts.fragment)))
print(orig_db)
print(target_db)
PY
)

MAINTENANCE_URL="${URLS[0]}"
TARGET_URL="${URLS[1]}"
SOURCE_DB_NAME="${URLS[2]}"
TARGET_DB_NAME="${URLS[3]}"

echo "Source DB : ${SOURCE_DB_NAME}"
echo "Target DB : ${TARGET_DB_NAME}"
echo "Backup    : ${BACKUP_FILE}"

if [[ "$DROP_IF_EXISTS" == "1" ]]; then
  echo "Dropping existing target database if present..."
  psql --dbname "$MAINTENANCE_URL" -v ON_ERROR_STOP=1 -c \
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '${TARGET_DB_NAME}' AND pid <> pg_backend_pid();" >/dev/null
  psql --dbname "$MAINTENANCE_URL" -v ON_ERROR_STOP=1 -c \
    "DROP DATABASE IF EXISTS \"${TARGET_DB_NAME}\";" >/dev/null
fi

echo "Creating target database..."
psql --dbname "$MAINTENANCE_URL" -v ON_ERROR_STOP=1 -c \
  "CREATE DATABASE \"${TARGET_DB_NAME}\";" >/dev/null

echo "Restoring backup into ${TARGET_DB_NAME} ..."
set +e
RESTORE_STDERR_FILE="$(mktemp -t yasargold_restore_dry_run_stderr.XXXXXX)"
pg_restore \
  --clean \
  --if-exists \
  --no-owner \
  --no-acl \
  --dbname "$TARGET_URL" \
  "$BACKUP_FILE" 2>"$RESTORE_STDERR_FILE"
RESTORE_EXIT=$?
set -e

if [[ "$RESTORE_EXIT" -ne 0 ]]; then
  if [[ "$PLAIN_SQL_FALLBACK" == "1" ]] && grep -Eqi 'text format dump|please use psql' "$RESTORE_STDERR_FILE"; then
    echo "Detected plain SQL dump. Falling back to psql..."
    psql --dbname "$TARGET_URL" -v ON_ERROR_STOP=1 -f "$BACKUP_FILE"
  else
    cat "$RESTORE_STDERR_FILE" >&2 || true
    rm -f "$RESTORE_STDERR_FILE"
    exit "$RESTORE_EXIT"
  fi
fi
rm -f "$RESTORE_STDERR_FILE"

echo "Running smoke checks..."
psql --dbname "$TARGET_URL" -v ON_ERROR_STOP=1 <<'SQL'
SELECT current_database() AS restored_database;
SELECT COUNT(*) AS public_tables
FROM information_schema.tables
WHERE table_schema = 'public';
SELECT COUNT(*) AS invoices_count FROM invoice;
SELECT COUNT(*) AS accounts_count FROM account;
SELECT COUNT(*) AS customers_count FROM customer;
SQL

echo "Dry run restore completed successfully."

if [[ "$KEEP_TEST_DB" != "1" ]]; then
  echo "Cleaning up target database..."
  psql --dbname "$MAINTENANCE_URL" -v ON_ERROR_STOP=1 -c \
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '${TARGET_DB_NAME}' AND pid <> pg_backend_pid();" >/dev/null
  psql --dbname "$MAINTENANCE_URL" -v ON_ERROR_STOP=1 -c \
    "DROP DATABASE IF EXISTS \"${TARGET_DB_NAME}\";" >/dev/null
  echo "Target database dropped."
else
  echo "Target database kept for inspection: ${TARGET_DB_NAME}"
fi
