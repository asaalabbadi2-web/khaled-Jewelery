"""Verify statement QR signatures (HMAC seal).

Usage examples:

  # 1) Paste the scanned QR JSON as an argument
  python backend/devtools/verify_statement_qr.py '{"algo":"HS256","signed":{...},"sig":"..."}'

  # 2) Or pipe from stdin
  pbpaste | python backend/devtools/verify_statement_qr.py

The script expects the same secret used by the backend to sign statements:
- Env var: QR_HMAC_SECRET
- Or pass: --secret "..."

Exit codes:
- 0: signature valid
- 2: signature invalid
- 1: error / missing signature
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import sys
from typing import Any


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sign(payload: dict[str, Any], *, secret: str) -> str:
    msg = _canonical_json(payload).encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _read_qr_text(positional: list[str]) -> str:
    if positional:
        return positional[0]

    data = sys.stdin.read()
    if not data.strip():
        raise SystemExit(
            "No QR payload provided. Pass it as an argument or pipe it via stdin."
        )
    return data


def _extract_signed_and_sig(obj: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None, str | None, str | None]:
    """Return (signed_payload, signature, algo, statement_id)."""

    statement_id = None
    if isinstance(obj.get("statement_id"), str):
        statement_id = obj.get("statement_id")

    algo = None
    if isinstance(obj.get("algo"), str):
        algo = obj.get("algo")
    elif isinstance(obj.get("alg"), str):
        algo = obj.get("alg")

    # Preferred wrapper format: { algo, signed, sig }
    if isinstance(obj.get("signed"), dict):
        signed = obj.get("signed")
        sig = obj.get("sig") or obj.get("signature") or obj.get("qr_signature")
        sig = (str(sig).strip() if sig is not None else None) or None
        return signed, sig, algo, statement_id

    # API-response style: { qr_signed_payload, qr_signature }
    if isinstance(obj.get("qr_signed_payload"), dict):
        signed = obj.get("qr_signed_payload")
        sig = obj.get("qr_signature") or obj.get("sig") or obj.get("signature")
        sig = (str(sig).strip() if sig is not None else None) or None
        return signed, sig, algo, statement_id

    return None, None, algo, statement_id


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Verify statement QR HMAC seal")
    parser.add_argument(
        "qr",
        nargs="?",
        help="QR JSON text (if omitted, read from stdin)",
    )
    parser.add_argument(
        "--secret",
        help="HMAC secret (defaults to env QR_HMAC_SECRET)",
    )

    args = parser.parse_args(argv)

    secret = (args.secret or os.environ.get("QR_HMAC_SECRET") or "").strip()
    if not secret:
        print(
            "ERROR: Missing secret. Set QR_HMAC_SECRET or pass --secret.",
            file=sys.stderr,
        )
        return 1

    qr_text = _read_qr_text([args.qr] if args.qr else [])
    try:
        obj = json.loads(qr_text)
    except Exception as exc:
        print(f"ERROR: QR text is not valid JSON: {exc}", file=sys.stderr)
        return 1

    if not isinstance(obj, dict):
        print("ERROR: QR JSON must be an object.", file=sys.stderr)
        return 1

    signed, sig, algo, statement_id = _extract_signed_and_sig(obj)
    if statement_id:
        print(f"Statement: {statement_id}")

    if not signed or not isinstance(signed, dict):
        print("No signed payload found in QR (unsigned / legacy QR).")
        return 1

    if not sig:
        print("No signature found in QR (unsigned / legacy QR).")
        return 1

    if algo and algo.strip().upper() not in ("HS256", "HMAC-SHA256"):
        print(f"WARNING: Unexpected algo: {algo}")

    expected = _sign(signed, secret=secret)
    if hmac.compare_digest(expected, sig):
        print("Signature Valid - Authentic Document")
        print("Arabic: التوقيع صحيح - الكشف أصلي")
        return 0

    print("Invalid Signature - Tampered Data")
    print("Arabic: التوقيع غير صحيح - بيانات QR قد تكون معدّلة")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
