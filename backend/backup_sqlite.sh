#!/usr/bin/env bash
set -euo pipefail

# SQLite backup for YasarGold (dev/local).
# Produces a consistent backup using Python's sqlite3 backup API.
# Usage:
#   ./backup_sqlite.sh
# Optional:
#   SQLITE_DB_PATH=/path/to/app.db BACKUP_DIR=/path/to/backups RETENTION_DAYS=14 ./backup_sqlite.sh

BACKEND_DIR="$(cd "$(dirname "$0")" && pwd)"
SQLITE_DB_PATH="${SQLITE_DB_PATH:-"$BACKEND_DIR/app.db"}"
BACKUP_DIR="${BACKUP_DIR:-"$BACKEND_DIR/../backups/sqlite"}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

umask 077
mkdir -p "$BACKUP_DIR"

if [[ ! -f "$SQLITE_DB_PATH" ]]; then
  echo "ERROR: SQLite DB not found: $SQLITE_DB_PATH" >&2
  exit 1
fi

TS="$(date -u +"%Y%m%dT%H%M%SZ")"
OUT_FILE="$BACKUP_DIR/yasargold_sqlite_${TS}.db"

python3 - <<PY
import sqlite3
src = r'''$SQLITE_DB_PATH'''
dst = r'''$OUT_FILE'''

src_conn = sqlite3.connect(src)
dst_conn = sqlite3.connect(dst)
try:
    src_conn.backup(dst_conn)
finally:
    dst_conn.close()
    src_conn.close()
print(dst)
PY

echo "OK: created backup: $OUT_FILE"

# Optional gzip
if command -v gzip >/dev/null 2>&1; then
  gzip -f "$OUT_FILE"
  OUT_FILE="$OUT_FILE.gz"
  echo "OK: compressed: $OUT_FILE"
fi

# Retention cleanup
if [[ "$RETENTION_DAYS" =~ ^[0-9]+$ ]] && [[ "$RETENTION_DAYS" -gt 0 ]]; then
  find "$BACKUP_DIR" -type f \( -name 'yasargold_sqlite_*.db' -o -name 'yasargold_sqlite_*.db.gz' \) -mtime "+$RETENTION_DAYS" -print -delete || true
fi
