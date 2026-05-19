#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(git rev-parse --show-toplevel)"
git config core.hooksPath ".githooks"
chmod +x "$ROOT_DIR/.githooks/pre-commit" "$ROOT_DIR/.githooks/pre-push"
echo "Installed git hooks from $ROOT_DIR/.githooks"