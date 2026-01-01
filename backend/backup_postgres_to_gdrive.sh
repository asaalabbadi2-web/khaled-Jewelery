#!/usr/bin/env bash
set -euo pipefail

# PostgreSQL backup -> (encrypted) upload to Google Drive via rclone.
# This is designed for the HYBRID on-prem server scenario.
#
# Recommended approach:
# - Configure rclone Google Drive remote (e.g. "gdrive")
# - Configure rclone crypt remote on top of it (e.g. "gdrive-crypt") for end-to-end encryption
# - Run this script hourly via cron/systemd.
#
# Required env vars:
#   DATABASE_URL=postgresql://user:pass@host:5432/dbname
#
# Required tools:
#   pg_dump (PostgreSQL client tools)
#   rclone
#
# Optional env vars:
#   BACKUP_DIR=...                  (default: ../backups/postgres)
#   RETENTION_DAYS=14               (local retention)
#   RCLONE_REMOTE=gdrive-crypt:yasargold/postgres
#   RCLONE_FLAGS="--transfers 2"     (extra rclone flags)
#   REMOTE_RETENTION_DAYS=90        (remote retention; 0 disables)

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
RCLONE_REMOTE="${RCLONE_REMOTE:-gdrive-crypt:yasargold/postgres}"
RCLONE_FLAGS="${RCLONE_FLAGS:-}"
REMOTE_RETENTION_DAYS="${REMOTE_RETENTION_DAYS:-90}"

umask 077
mkdir -p "$BACKUP_DIR"

if ! command -v pg_dump >/dev/null 2>&1; then
  echo "ERROR: pg_dump not found. Install PostgreSQL client tools on the server." >&2
  exit 1
fi

if ! command -v rclone >/dev/null 2>&1; then
  echo "ERROR: rclone not found. Install rclone on the server." >&2
  exit 1
fi

TS="$(date -u +"%Y%m%dT%H%M%SZ")"
OUT_FILE="$BACKUP_DIR/yasargold_pg_${TS}.dump"

# Create dump (custom format is compressed and restore-friendly)
pg_dump \
  --format=custom \
  --no-owner \
  --no-acl \
  --dbname "$DATABASE_URL" \
  --file "$OUT_FILE"

echo "OK: created backup: $OUT_FILE"

# Upload to remote (encrypted if using rclone crypt remote)
# rclone copy copies file(s) into the destination folder
rclone copy "$OUT_FILE" "$RCLONE_REMOTE" $RCLONE_FLAGS

echo "OK: uploaded to remote: $RCLONE_REMOTE"

# Local retention cleanup
if [[ "$RETENTION_DAYS" =~ ^[0-9]+$ ]] && [[ "$RETENTION_DAYS" -gt 0 ]]; then
  find "$BACKUP_DIR" -type f -name 'yasargold_pg_*.dump' -mtime "+$RETENTION_DAYS" -print -delete || true
fi

# Remote retention cleanup (best-effort)
# Deletes remote files older than N days.
if [[ "$REMOTE_RETENTION_DAYS" =~ ^[0-9]+$ ]] && [[ "$REMOTE_RETENTION_DAYS" -gt 0 ]]; then
  # --min-age applies to the remote object's modtime.
  # We keep this best-effort (do not fail backups on remote cleanup errors).
  rclone delete "$RCLONE_REMOTE" --min-age "${REMOTE_RETENTION_DAYS}d" $RCLONE_FLAGS || true
fi
