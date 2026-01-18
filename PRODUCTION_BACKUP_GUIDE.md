# Production Backup Guide (Yasar Gold)

This guide covers safe production rollout for the in-app backup/restore + cloud backup + encryption.

## 1) Google Drive (OAuth) Checklist

- [ ] Google Cloud Project created for **production**.
- [ ] **Google Drive API** enabled.
- [ ] OAuth Consent Screen:
  - [ ] Publishing status: **Production** (not Testing) to avoid 7-day token expiry.
  - [ ] Scopes: use least privilege, recommended: `https://www.googleapis.com/auth/drive.file`.
  - [ ] If you have >100 external users: complete Google verification requirements.
- [ ] OAuth Client IDs created per platform:
  - [ ] Android client ID (package name + SHA-1/256).
  - [ ] iOS client ID (bundle id).
  - [ ] Web client ID (if deploying Flutter Web).

## 2) Encryption & Data Integrity

- **Algorithm**: AES-256-GCM.
- **KDF (password mode)**: PBKDF2-HMAC-SHA256.
  - Current iterations: **150,000** (in [frontend/lib/services/backup_encryption_service.dart](frontend/lib/services/backup_encryption_service.dart)).
- **Integrity**:
  - `.ygbak` now embeds a SHA-256 hash of the decrypted ZIP and verifies it on decrypt.
  - If hash mismatch occurs, treat it as corruption/tampering and abort restore.

### Key management modes (important)

- **Password mode**: restore works on any device, but password cannot be recovered.
- **Device key mode**: no password prompt, but restore is only possible on the same device that created the key.

## 3) Backend Safety (Restore Policy)

### Environment guard

- Keep `ALLOW_DANGEROUS_RESETS=false` in production by default.
- Enable it only during a controlled maintenance window:
  - `ALLOW_DANGEROUS_RESETS=true`
  - Perform restore
  - Return to `ALLOW_DANGEROUS_RESETS=false`

### Docker volumes (important)

- For Docker deployments, set `BACKUP_DIR=/data/backups` and mount it as a persistent volume.
  This is where the backend stores pre-restore snapshots and `restore_audit.log`.

### PostgreSQL support

- In production, `docker-compose.prod.yml` uses PostgreSQL.
- In-app backup/restore uses `pg_dump`/`pg_restore` inside the backend container.
  Ensure the backend image includes PostgreSQL client tools (this repo's backend Dockerfile installs them).

### Server-side snapshot before restore

- Every restore takes a **pre-restore snapshot** ZIP on the server filesystem.
- Snapshot path:
  - Default: `backend/backups/pre-restore-snapshot-*.zip`
  - Override: set `BACKUP_DIR=/safe/path`

Note: When using Nginx (Flutter Web container), make sure `client_max_body_size` allows your backup ZIP upload size.

### Audit logging (persistent)

- Every restore attempt (blocked/rejected/failed/succeeded) is appended to:
  - `BACKUP_DIR/restore_audit.log` (default: `backend/backups/restore_audit.log`)

## 4) Maintenance Window (Operational Playbook)

- [ ] Announce downtime (restore replaces all data).
- [ ] Stop client activity (no posting/invoicing during restore).
- [ ] Take an extra manual backup (download ZIP or encrypted `.ygbak`).
- [ ] Run restore.
- [ ] Restart backend services.
- [ ] Re-open the system.

Note: “Disconnect active users” requires an application-level session invalidation strategy (JWT revocation/redis/session store). If needed, implement it as a dedicated feature (recommended for larger deployments).

## 5) UI Guard (Frontend)

Restore buttons are disabled unless:
- User role is **System Admin**.
- Server allows dangerous resets (or is not production), as reported by `/api/system/reset/info`.

## 6) Production App Branding

- App display name is set to `Khaled Jewelery` for Android/iOS/Web.
- To apply the provided logo as the launcher icon:
  1) Put the PNG at `frontend/assets/KHGL.png` (recommended 1024x1024).
  2) Run:
     - `cd frontend`
     - `flutter pub get`
     - `dart run flutter_launcher_icons`
