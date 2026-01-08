# Development Quick Start

This file documents quick commands and helper scripts for a flexible local development environment.

1) Start backend (venv)

```bash
./scripts/dev-backend.sh --venv
```

This creates/uses `backend/venv`, installs requirements and runs `python app.py`. If you prefer Docker:

```bash
./scripts/dev-backend.sh --docker
```

2) Start frontend (Flutter web) with local API and optional auth bypass

```bash
./scripts/dev-frontend.sh --api http://127.0.0.1:8001/api
```

To disable the auth bypass for testing real auth flows:

```bash
./scripts/dev-frontend.sh --api http://127.0.0.1:8001/api --no-bypass
```

3) Import Chart of Accounts

- We produced `exports/accounts_import.json` (mapping keyed by `account_number`).
- Preferred: run frontend with `BYPASS_AUTH_FOR_DEVELOPMENT=true` then use the Chart of Accounts import UI.
- Alternatively, obtain a JWT and call the API:

```bash
# get a token via login
curl -sS -X POST http://127.0.0.1:8001/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin"}'

# replace TOKEN and run import
curl -X POST http://127.0.0.1:8001/api/accounts/import \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  --data-binary @exports/accounts_import.json
```

4) Reset admin (destructive)

If you cannot log in and accept deactivating other users:

```bash
cd backend
python reset_admin_user.py --yes --password admin
```

Notes
- Scripts are lightweight helpers; mark them executable:

```bash
chmod +x scripts/*.sh
```

If you want, I can commit `scripts/` and `README_DEV.md` (done), and then either run the import for you (requires token or admin reset) or run the frontend with bypass and verify the import via UI. Tell me which you prefer.
