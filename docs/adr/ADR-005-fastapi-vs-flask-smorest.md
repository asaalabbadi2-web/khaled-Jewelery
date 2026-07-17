# ADR-005: FastAPI (not flask-smorest) for Commerce API

**Status**: Accepted  
**Date**: 2026-07-12

## Context

The Commerce API is a new public-facing service that will be exposed to the internet. The ERP is built on Flask. We evaluated adding a Flask blueprint (or flask-smorest) to the existing Flask app vs. building a separate FastAPI service.

## Decision

Build `apps/commerce-api` as a standalone **FastAPI** service, not a Flask extension.

Three concrete reasons:

1. **Pydantic at the boundary.** FastAPI + Pydantic collapses schema, contract, and input validation into one definition. With flask-smorest we would maintain a marshmallow schema and a separate contract — two things that can drift. Every field in `schemas.py` is simultaneously the OpenAPI schema and the runtime validator.

2. **Physical isolation from the ERP.** Different framework = different Python import tree. import-linter can enforce that `yasargold_domain` never imports `flask`, but if Commerce API ran as a Flask blueprint it would share the same process and the same `current_app`, making isolation a convention rather than a constraint. A separate process is a hard boundary.

3. **Low learning cost.** The Commerce API is intentionally thin — it reads data and delegates all logic to `yasargold_domain`. FastAPI routing is simpler to reason about than Flask's application factory + blueprint registration when the app is this small.

## Consequences

- Commerce API runs as a separate process (different port in dev, separate container in prod)
- OpenAPI spec is generated automatically via `/openapi.json`; the generated file is committed to `packages/contracts/` and CI fails if it drifts
- import-linter contract "domain must not import framework code" blocks Flask, FastAPI, Redis, and Uvicorn from ever appearing in `yasargold_domain` or `yasargold_platform`

## Rejected Alternative

**flask-smorest on the existing Flask app**: would have required the ERP to be internet-facing, violating Principle 1.3 (ERP stays behind the internal network). Schema drift between marshmallow objects and OpenAPI output is an operational risk we have already paid in the ERP codebase and chose not to carry into new services.
