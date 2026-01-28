# Production Deployment Guide (Best Practice baseline)

Target: Linux VPS + Docker Compose + PostgreSQL + migrations + small maintenance window (1–5 minutes).

## 0) Prerequisites on the VPS
- Docker + Docker Compose plugin installed
- Firewall allows inbound 80/443
- A domain name pointing to the VPS (recommended)

## 1) Prepare environment
1. Copy `.env.production.example` to `.env.production` and fill real values:
   - Set strong `POSTGRES_PASSWORD`
   - Set strong `JWT_SECRET_KEY`
   - If using managed Postgres, set `DATABASE_URL` accordingly

2. Frontend build is baked into the `nginx` image (Flutter Web inside Docker).
   - In CI/CD, build/push the Docker images.
   - On the server, you will `pull` and `up -d` the updated images.

### Optional: Google Drive Backups via Service Account
If you want server-side Google Drive backups (works on IP-only / HTTP deployments without browser OAuth):

1. **Create a Google Service Account**:
   - Go to Google Cloud Console → IAM & Admin → Service Accounts
   - Create a new Service Account
   - Enable **Google Drive API** for the project
   - Create a JSON key and download it

2. **Create a dedicated Drive folder**:
   - In Google Drive, create a folder for backups (e.g., "YasarGold Backups")
   - Share the folder with the Service Account email (give Editor permissions)
   - Copy the folder ID from the URL (e.g., `https://drive.google.com/drive/folders/1abc...xyz` → `1abc...xyz`)

3. **Configure on the server**:
   - Create a `secrets/` directory in your project root:
     ```bash
     mkdir -p secrets
     chmod 700 secrets
     ```
   - Place the Service Account JSON key:
     ```bash
     cp ~/google_drive_sa.json ./secrets/google_drive_sa.json
     chmod 400 ./secrets/google_drive_sa.json
     ```
   - Add to `.env.production`:
     ```bash
     GOOGLE_DRIVE_BACKUP_FOLDER_ID=1abc...xyz
     GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE=/run/secrets/google_drive_sa.json
     ```

4. **Important security notes**:
   - Keep the Service Account JSON file secure (read-only, restricted access)
   - Never commit it to git (already in `.gitignore`)
   - Backups uploaded via Service Account are **not end-to-end encrypted** by default
   - For E2EE, continue using rclone with crypt (see `BACKUP_RESTORE_GUIDE.md`)

After setup:
- The backend will expose Drive backup endpoints: `/api/system/backup/drive/*`
- Users with `system.backup` or `system.settings` permission can use the UI to upload/list/download backups

## 2) First-time start (staging first recommended)
1. Start DB + backend + nginx:
   - `docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build`

2. Run migrations (maintenance step):
   - `docker compose -f docker-compose.prod.yml --env-file .env.production run --rm backend alembic upgrade head`

3. Verify:
   - `curl -f http://127.0.0.1/api/gold_price` (or via domain)

## 3) Update workflow (safe, repeatable)
Recommended steps for each release:
1. Back up Postgres (see `BACKUP_RESTORE_GUIDE.md`)
2. Pull latest code / artifacts to the server
3. Deploy containers:
   - If using CI/CD pushed images (recommended):
     - `docker compose -f docker-compose.prod.images.yml --env-file .env.production pull`
     - `docker compose -f docker-compose.prod.images.yml --env-file .env.production up -d`
   - Or build on the server (acceptable early on):
     - `docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build`
4. Apply migrations:
    - If using CI/CD pushed images:
       - `docker compose -f docker-compose.prod.images.yml --env-file .env.production run --rm backend alembic upgrade head`
    - If building on the server:
       - `docker compose -f docker-compose.prod.yml --env-file .env.production run --rm backend alembic upgrade head`

## 3.1) Auto-Deploy (GitHub Actions -> SSH -> VPS)
This repo includes an optional production auto-deploy workflow: `.github/workflows/deploy-prod.yml`.

Important notes:
- Keep runtime secrets on the VPS only (e.g. `.env.production` with `JWT_SECRET_KEY`, `POSTGRES_PASSWORD`).
- For private GHCR images, the VPS must authenticate to GHCR to pull images.
- Do one manual deploy first to validate `.env.production` and database connectivity.

### Required GitHub Secrets
Add these in: Settings -> Secrets and variables -> Actions -> Secrets
- `SSH_PRIVATE_KEY`: SSH private key that can access the VPS
- `VPS_HOST`: VPS IP/hostname
- `VPS_USER`: SSH username (prefer a limited user with Docker permissions)
- `GHCR_PAT`: Personal Access Token with `read:packages` (for pulling private images)

### Required GitHub Variable
Add this in: Settings -> Secrets and variables -> Actions -> Variables
- `PROJECT_PATH`: path on the VPS where this repo (and `docker-compose.prod.images.yml`) lives, e.g. `/var/www/yasargold`

### What the workflow does
On merge/push to `main`:
1. Builds & pushes images to GHCR (via `.github/workflows/docker-images.yml`)
2. SSH into the VPS
3. `docker login ghcr.io` using `GHCR_PAT`
4. `docker compose pull` then `up -d`
5. Runs migrations: `alembic upgrade head`

## 4) HTTPS
For production HTTPS, use a reverse proxy with automatic certificates (Caddy/Traefik) or terminate TLS at Nginx.
This repo keeps the nginx container minimal; add TLS termination as the next step.

## 5) Notes
- Do NOT use `BYPASS_AUTH_FOR_DEVELOPMENT` in production.
- Keep `.env.production` out of git.
- Consider a staging VPS that mirrors production.
