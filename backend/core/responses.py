"""Flask response helpers — decorators and standard error shapes."""
from __future__ import annotations

import os
from functools import wraps

from flask import current_app, jsonify


def wrap_api_exceptions(error_code: str, message: str):
    """Decorator: catch any exception and return a uniform JSON 500 response."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except Exception as exc:
                try:
                    current_app.logger.exception('%s', error_code)
                except Exception:
                    pass
                expose = (os.getenv('EXPOSE_API_ERRORS') or '').strip() == '1'
                payload = {'error': error_code, 'message': message}
                if 'account_id' in kwargs:
                    payload['account_id'] = kwargs['account_id']
                if expose:
                    payload['details'] = str(exc)
                return jsonify(payload), 500
        return wrapper
    return decorator


# Private alias kept for backward compat with routes/__init__.py re-export.
_wrap_api_exceptions = wrap_api_exceptions
