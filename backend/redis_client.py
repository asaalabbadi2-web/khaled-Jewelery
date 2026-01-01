"""Optional Redis client helper.

Redis is used as an acceleration layer for:
- login rate limiting counters
- token blacklist cache (jti)
- refresh session cache (token hashes)

The application must continue to work without Redis.
"""

from __future__ import annotations

import os
from typing import Optional


def get_redis_url() -> str:
    return (os.getenv('REDIS_URL') or '').strip()


def get_redis() -> Optional[object]:
    url = get_redis_url()
    if not url:
        return None

    try:
        import redis  # type: ignore
    except Exception:
        return None

    try:
        client = redis.Redis.from_url(url, decode_responses=True)
        # Cheap connectivity check; if it fails we treat Redis as unavailable.
        client.ping()
        return client
    except Exception:
        return None
