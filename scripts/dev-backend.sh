#!/usr/bin/env bash
set -euo pipefail

# Dev helper: run backend in venv or via docker-compose
# Usage: ./scripts/dev-backend.sh [--venv] [--docker]

USE_VENV=true
USE_DOCKER=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --docker)
      USE_DOCKER=true
      USE_VENV=false
      shift
      ;;
    --venv)
      USE_VENV=true
      USE_DOCKER=false
      shift
      ;;
    *)
      echo "Unknown arg: $1" >&2
      exit 1
      ;;
  esac
done

if [ "$USE_DOCKER" = true ]; then
  echo "Starting backend with docker-compose using .env.development"
  docker compose --env-file .env.development up --build
  exit 0
fi

echo "Starting backend using venv"
if [ ! -d "backend/venv" ]; then
  echo "Creating venv under backend/venv"
  python3 -m venv backend/venv
fi
source backend/venv/bin/activate
pip install -r backend/requirements.txt || true

# Load .env.development if present
if [ -f .env.development ]; then
  echo "Exporting .env.development"
  export $(grep -v '^#' .env.development | xargs)
fi

cd backend
python app.py
