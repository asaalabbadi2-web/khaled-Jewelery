# Permissions Endpoint Coverage Report
Generated: 2025-12-29 02:34:08
This report checks only endpoints defined in `backend/routes.py` under the `api` blueprint.
Coverage rules (static analysis):
- If an endpoint has an explicit `@require_permission('code')` decorator and `code` exists in the catalog, it is considered **covered**.
- Otherwise, we fall back to the conservative inference logic mirrored from `backend/routes.py::_infer_permission_code`.
- If neither explicit coverage nor inference yields a catalog permission, it is listed as **unknown / uncovered**.
## Summary
| Metric | Value |
|---|---:|
| Permission codes in catalog (from `*_PERMISSIONS`) | 60 |
| @api.route endpoints in `backend/routes.py` | 131 |
| Covered method entries (method+path) | 131 |
| Unknown method entries (method+path) | 0 |
| Unknown resource groups | 0 |

## Unknown / Uncovered endpoints
These endpoints currently do **not** map to any permission in the catalog under the current inference rules.
Most common reasons:
- The endpoint is for a resource not in `_PERMISSION_RESOURCE_MAP`
- It is an action endpoint (eg. `/post`, `/approve`, `/cancel`, `/backup`) not mapped to `*.edit`/`*.delete`/etc
- The catalog has a permission (eg. `journal.post`) but inference does not return it

## Notes
- If `BYPASS_AUTH_FOR_DEVELOPMENT` is enabled, permission enforcement may appear to be bypassed during testing.
- Next step is typically either: (1) add missing permission codes to the catalog, and/or (2) extend `_infer_permission_code` to recognize additional action endpoints (eg. `journal.post`).
