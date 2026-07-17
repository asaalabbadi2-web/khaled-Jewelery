# ADR-004: uv Workspaces for Monorepo Dependency Management

**Status**: Accepted  
**Date**: 2026-07-12

## Context

The platform is evolving from a single Flask monolith (`backend/`) into a multi-app monorepo:
- `packages/platform` — infrastructure utilities (no framework)
- `packages/domain` — business logic (no framework)
- `apps/erp` — Flask ERP (internal network only)
- `apps/commerce-api` — FastAPI public API

We need shared packages to be installable by multiple apps without being published to PyPI, and without pip path-dependency hacks that break in CI.

## Decision

Use **uv workspaces** (declared in the root `pyproject.toml`) with `{ workspace = true }` sources in each app's `pyproject.toml`.

## Consequences

- Single `uv sync --all-packages` installs the entire workspace into one `.venv`
- Workspace packages are editable by default — no reinstall needed after edits
- `uv.lock` is a single file at the repo root, giving reproducible installs across all apps
- Import-linter contracts run against the combined PYTHONPATH of all workspace packages

## Rejected Alternatives

**pip path deps** (`pip install -e ../packages/domain`): breaks in CI without careful ordering; produces no lockfile.

**Published packages on PyPI**: adds a release pipeline for internal-only code; forces version bumps on every cross-package change.

**Monkeypatching sys.path**: fragile, invisible to tooling, fails in production containers.
