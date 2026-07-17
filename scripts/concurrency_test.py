#!/usr/bin/env python3
"""Concurrency test for POST /api/v1/reservations.

Fires N simultaneous requests for the same item_slug and verifies:
  - Exactly 1 request succeeds (HTTP 201)
  - All others fail with HTTP 409 (ITEM_ALREADY_RESERVED)
  - No unexpected status codes

Usage:
    # Default: 20 concurrent requests against local server
    python scripts/concurrency_test.py

    # Against staging with 50 concurrent requests:
    python scripts/concurrency_test.py \\
        --url https://staging-api.yasargold.com \\
        --concurrency 50 \\
        --slug yg001

Requirements:
    pip install httpx   (already in .venv)

Exit codes:
    0 — test passed (exactly 1 success, rest are 409)
    1 — test failed (unexpected results)
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import httpx
except ImportError:
    print("ERROR: httpx not installed. Run: pip install httpx")
    sys.exit(1)


def _post_reservation(url: str, item_slug: str, index: int) -> dict:
    """Send one POST /reservations request. Returns result dict."""
    start = time.perf_counter()
    try:
        resp = httpx.post(
            f"{url}/api/v1/reservations",
            json={"item_slug": item_slug},
            timeout=10.0,
        )
        elapsed_ms = (time.perf_counter() - start) * 1000
        return {
            "index": index,
            "status": resp.status_code,
            "body": resp.json(),
            "elapsed_ms": elapsed_ms,
        }
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start) * 1000
        return {
            "index": index,
            "status": -1,
            "body": {"error": str(exc)},
            "elapsed_ms": elapsed_ms,
        }


def run_test(url: str, item_slug: str, concurrency: int) -> bool:
    print(f"\n{'='*60}")
    print(f"Concurrency test: POST /api/v1/reservations")
    print(f"  URL:         {url}")
    print(f"  item_slug:   {item_slug}")
    print(f"  concurrency: {concurrency}")
    print(f"{'='*60}\n")

    results = []
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [
            pool.submit(_post_reservation, url, item_slug, i)
            for i in range(concurrency)
        ]
        for f in as_completed(futures):
            results.append(f.result())

    results.sort(key=lambda r: r["index"])

    # Count status codes
    statuses = Counter(r["status"] for r in results)
    print("Status code distribution:")
    for code, count in sorted(statuses.items()):
        marker = "✅" if code in (201, 409) else "❌"
        print(f"  {marker} HTTP {code}: {count} requests")

    # Timing
    elapsed_values = [r["elapsed_ms"] for r in results if r["status"] != -1]
    if elapsed_values:
        elapsed_values.sort()
        n = len(elapsed_values)
        p50 = elapsed_values[n // 2]
        p95 = elapsed_values[int(n * 0.95)]
        p99 = elapsed_values[int(n * 0.99)]
        print(f"\nLatency (ms):  P50={p50:.0f}  P95={p95:.0f}  P99={p99:.0f}")

    # Validate: exactly 1 success
    success_count = statuses.get(201, 0)
    conflict_count = statuses.get(409, 0)
    unexpected = {k: v for k, v in statuses.items() if k not in (201, 409)}

    print(f"\n{'='*60}")
    passed = True

    if success_count == 1:
        print(f"✅ Exactly 1 reservation succeeded")
        winner = next(r for r in results if r["status"] == 201)
        print(f"   reservation_id: {winner['body'].get('reservation_id', '?')}")
        print(f"   quote_id:       {winner['body'].get('quote_id', '?')}")
    else:
        print(f"❌ Expected 1 success, got {success_count}")
        passed = False

    if conflict_count == concurrency - 1:
        print(f"✅ {conflict_count} requests correctly received 409 CONFLICT")
    else:
        print(f"❌ Expected {concurrency - 1} conflicts, got {conflict_count}")
        passed = False

    if unexpected:
        print(f"❌ Unexpected status codes: {unexpected}")
        passed = False

    # Print 409 error codes to verify ITEM_ALREADY_RESERVED
    conflict_codes = [
        r["body"].get("detail", {}).get("code")
        for r in results
        if r["status"] == 409
    ]
    unique_conflict_codes = set(conflict_codes) - {None}
    if unique_conflict_codes == {"ITEM_ALREADY_RESERVED"}:
        print(f"✅ All 409s carry code=ITEM_ALREADY_RESERVED")
    elif conflict_codes:
        print(f"⚠️  409 codes: {unique_conflict_codes}")

    print(f"\n{'='*60}")
    result_str = "PASSED ✅" if passed else "FAILED ❌"
    print(f"Result: {result_str}")
    return passed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:8000",
                        help="Base URL of the Commerce API")
    parser.add_argument("--slug", default="yg001",
                        help="Item slug to test against")
    parser.add_argument("--concurrency", type=int, default=20,
                        help="Number of simultaneous requests")
    args = parser.parse_args()

    passed = run_test(args.url, args.slug, args.concurrency)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
