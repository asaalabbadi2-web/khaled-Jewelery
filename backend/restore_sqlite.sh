#!/usr/bin/env bash
set -euo pipefail

# SQLite restore for YasarGold (dev/local).
# Usage:
#   CONFIRM_RESTORE=YES BACKUP_FILE=/path/to/yasargold_sqlite_....db.gz ./restore_sqlite.sh
# Optional:
#   SQLITE_DB_PATH=/path/to/app.db

if [[ "${CONFIRM_RESTORE:-}" != "YES" ]]; then
  echo "ERROR: set CONFIRM_RESTORE=YES to proceed" >&2
  exit 1
fi

BACKEND_DIR="$(cd "$(dirname "$0")" && pwd)"
SQLITE_DB_PATH="${SQLITE_DB_PATH:-"$BACKEND_DIR/app.db"}"

if [[ -z "${BACKUP_FILE:-}" ]]; then
  echo "ERROR: BACKUP_FILE is not set" >&2
  exit 1
fi

if [[ ! -f "$BACKUP_FILE" ]]; then
  echo "ERROR: backup file not found: $BACKUP_FILE" >&2
  exit 1
fi

# Make a safety copy of current DB (if exists)
if [[ -f "$SQLITE_DB_PATH" ]]; then
  TS="$(date -u +"%Y%m%dT%H%M%SZ")"
  cp -p "$SQLITE_DB_PATH" "$SQLITE_DB_PATH.before_restore_${TS}" || true
  echo "Saved current DB snapshot: $SQLITE_DB_PATH.before_restore_${TS}"
fi

TMP_FILE=""
if [[ "$BACKUP_FILE" == *.gz ]]; then
  if ! command -v gzip >/dev/null 2>&1; then
    echo "ERROR: gzip not found to decompress: $BACKUP_FILE" >&2
    exit 1
  fi
  TMP_FILE="$(mktemp -t yasargold_sqlite_restore.XXXXXX).db"
  gzip -dc "$BACKUP_FILE" > "$TMP_FILE"
  cp -f "$TMP_FILE" "$SQLITE_DB_PATH"
  rm -f "$TMP_FILE"
else
  cp -f "$BACKUP_FILE" "$SQLITE_DB_PATH"
fi

echo "OK: restored SQLite DB to: $SQLITE_DB_PATH"
echo "Next: restart backend server"
