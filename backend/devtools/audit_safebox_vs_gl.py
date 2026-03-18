"""Audit SafeBoxTransaction vs posted GL (journal_entry_line) for cash safes.

Goal
- Detect drift early so it doesn't accumulate.
- Provide a deterministic, repeatable check that can be run nightly.

Notes
- Some SafeBoxTransaction rows are intentionally "ledger-only" and should not be
  compared to GL (e.g. shift_closing_settlement).
- Legacy pattern: SafeBoxTransaction(ref_type='invoice_payment') may have ref_id=voucher.id.
  For GL-key comparison we normalize those rows as voucher/ref_id when invoice_payment_id is set
  and ref_id != invoice_payment_id.

Usage
  python -m devtools.audit_safebox_vs_gl
  python -m devtools.audit_safebox_vs_gl --safe-box-id 38
  python -m devtools.audit_safebox_vs_gl --exit-nonzero
"""

from __future__ import annotations

import argparse
import os
import sys

from flask import Flask
from sqlalchemy import bindparam, text

# Ensure backend/ is importable when running from other working directories.
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from models import db


def _normalize_database_url(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        return value
    if value.startswith("postgres://"):
        value = "postgresql://" + value[len("postgres://") :]
    if value.startswith("sqlite:///") and not value.startswith("sqlite:////"):
        sqlite_path = value[len("sqlite:///") :]
        if sqlite_path and not sqlite_path.startswith("/") and "/" not in sqlite_path and "\\" not in sqlite_path:
            abs_path = os.path.abspath(os.path.join(BACKEND_DIR, sqlite_path))
            return f"sqlite:///{abs_path}"
    return value


def _create_app() -> Flask:
    app = Flask(__name__)
    default_sqlite = f"sqlite:///{os.path.join(BACKEND_DIR, 'app.db')}"
    app.config["SQLALCHEMY_DATABASE_URI"] = _normalize_database_url(os.getenv("DATABASE_URL", default_sqlite))
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)
    return app


def _parse_csv(raw: str | None) -> list[str]:
    if not raw:
        return []
    parts = [p.strip() for p in str(raw).replace(";", ",").split(",")]
    return [p for p in parts if p]


def _audit(*, safe_box_id: int | None, ignore_ref_types: list[str]) -> tuple[list[dict], list[dict]]:
    ignore_norm = [x.strip().lower() for x in ignore_ref_types if x and x.strip()]

    params: dict = {"ignore": ignore_norm}
    safe_filter_gl = ""
    safe_filter_sb = ""
    if safe_box_id is not None:
        params["sid"] = int(safe_box_id)
        safe_filter_gl = " AND sbx.id = :sid "
        safe_filter_sb = " AND sb.safe_box_id = :sid "

    # Summary totals.
    summary_rows = (
        db.session.execute(
            text(
                "WITH sb AS (\n"
                "  SELECT safe_box_id,\n"
                "    SUM(CASE WHEN direction='in' THEN COALESCE(amount_cash,0) ELSE -COALESCE(amount_cash,0) END)::numeric(18,2) AS sb_total\n"
                "  FROM safe_box_transaction sb\n"
                "  WHERE (LOWER(TRIM(COALESCE(ref_type,''))) NOT IN :ignore) "
                + safe_filter_sb
                + "  GROUP BY safe_box_id\n"
                "),\n"
                "gl AS (\n"
                "  SELECT sbx.id AS safe_box_id,\n"
                "    SUM(COALESCE(jel.cash_debit,0) - COALESCE(jel.cash_credit,0))::numeric(18,2) AS gl_total\n"
                "  FROM journal_entry je\n"
                "  JOIN journal_entry_line jel ON jel.journal_entry_id = je.id\n"
                "  JOIN safe_box sbx ON sbx.account_id = jel.account_id\n"
                "  WHERE COALESCE(jel.is_deleted,false)=false\n"
                "    AND COALESCE(je.is_deleted,false)=false\n"
                "    AND COALESCE(je.is_draft,false)=false\n"
                "    AND COALESCE(je.is_posted,true)=true\n"
                + safe_filter_gl
                + "  GROUP BY sbx.id\n"
                ")\n"
                "SELECT COALESCE(sb.safe_box_id, gl.safe_box_id) AS safe_box_id,\n"
                "  COALESCE(sb.sb_total,0) AS sb_total,\n"
                "  COALESCE(gl.gl_total,0) AS gl_total,\n"
                "  (COALESCE(sb.sb_total,0) - COALESCE(gl.gl_total,0)) AS diff\n"
                "FROM sb FULL OUTER JOIN gl ON gl.safe_box_id = sb.safe_box_id\n"
                "ORDER BY ABS(COALESCE(sb.sb_total,0) - COALESCE(gl.gl_total,0)) DESC"
            ).bindparams(bindparam("ignore", expanding=True)),
            params,
        )
        .mappings()
        .all()
    )

    # Keyed diff with normalization for legacy invoice_payment rows.
    keyed_rows = (
        db.session.execute(
            text(
                "WITH gl_keyed AS (\n"
                "  SELECT\n"
                "    CASE WHEN LOWER(TRIM(COALESCE(je.reference_type,'')))='' THEN 'journal_entry'\n"
                "         ELSE LOWER(TRIM(COALESCE(je.reference_type,''))) END AS ref_type,\n"
                "    CASE WHEN LOWER(TRIM(COALESCE(je.reference_type,'')))='' OR COALESCE(je.reference_id,0)=0 THEN je.id\n"
                "         ELSE je.reference_id::int END AS ref_id,\n"
                "    SUM((COALESCE(jel.cash_debit,0) - COALESCE(jel.cash_credit,0)))::numeric(18,2) AS gl_signed\n"
                "  FROM journal_entry_line jel\n"
                "  JOIN journal_entry je ON je.id = jel.journal_entry_id\n"
                "  JOIN safe_box sbx ON sbx.account_id = jel.account_id\n"
                "  WHERE COALESCE(jel.is_deleted,false)=false\n"
                "    AND COALESCE(je.is_deleted,false)=false\n"
                "    AND COALESCE(je.is_draft,false)=false\n"
                "    AND COALESCE(je.is_posted,true)=true\n"
                + safe_filter_gl
                + "  GROUP BY 1,2\n"
                "),\n"
                "sb_keyed AS (\n"
                "  SELECT\n"
                "    CASE\n"
                "      WHEN LOWER(TRIM(COALESCE(ref_type,'')))='invoice_payment'\n"
                "       AND COALESCE(invoice_payment_id,0)<>0\n"
                "       AND COALESCE(ref_id,0)<>0\n"
                "       AND ref_id<>invoice_payment_id\n"
                "        THEN 'voucher'\n"
                "      ELSE LOWER(TRIM(COALESCE(ref_type,'')))\n"
                "    END AS ref_type,\n"
                "    CASE\n"
                "      WHEN LOWER(TRIM(COALESCE(ref_type,'')))='invoice_payment'\n"
                "       AND COALESCE(invoice_payment_id,0)<>0\n"
                "       AND COALESCE(ref_id,0)<>0\n"
                "       AND ref_id<>invoice_payment_id\n"
                "        THEN ref_id::int\n"
                "      ELSE ref_id::int\n"
                "    END AS ref_id,\n"
                "    SUM(CASE WHEN direction='in' THEN COALESCE(amount_cash,0) ELSE -COALESCE(amount_cash,0) END)::numeric(18,2) AS sb_signed\n"
                "  FROM safe_box_transaction sb\n"
                "  WHERE (LOWER(TRIM(COALESCE(ref_type,''))) NOT IN :ignore) "
                + safe_filter_sb
                + "  GROUP BY 1,2\n"
                ")\n"
                "SELECT\n"
                "  COALESCE(sb.ref_type, gl.ref_type) AS ref_type,\n"
                "  COALESCE(sb.ref_id, gl.ref_id) AS ref_id,\n"
                "  COALESCE(sb.sb_signed,0) AS sb_signed,\n"
                "  COALESCE(gl.gl_signed,0) AS gl_signed,\n"
                "  (COALESCE(sb.sb_signed,0) - COALESCE(gl.gl_signed,0)) AS diff\n"
                "FROM sb_keyed sb\n"
                "FULL OUTER JOIN gl_keyed gl\n"
                "  ON gl.ref_type = sb.ref_type AND gl.ref_id = sb.ref_id\n"
                "WHERE abs(COALESCE(sb.sb_signed,0) - COALESCE(gl.gl_signed,0)) > 0.009\n"
                "ORDER BY abs(COALESCE(sb.sb_signed,0) - COALESCE(gl.gl_signed,0)) DESC, ref_type, ref_id\n"
            ).bindparams(bindparam("ignore", expanding=True)),
            params,
        )
        .mappings()
        .all()
    )

    return [dict(r) for r in summary_rows], [dict(r) for r in keyed_rows]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--safe-box-id", type=int, default=None)
    parser.add_argument(
        "--ignore-ref-types",
        type=str,
        default="shift_closing_settlement",
        help="Comma-separated SafeBoxTransaction.ref_type values to ignore in comparison",
    )
    parser.add_argument("--exit-nonzero", action="store_true", help="Exit with code 1 when any mismatch exists")
    args = parser.parse_args()

    ignore = _parse_csv(args.ignore_ref_types)

    app = _create_app()
    with app.app_context():
        summary, keyed = _audit(safe_box_id=args.safe_box_id, ignore_ref_types=ignore)

        print("=== SafeBox totals (SB vs GL) ===")
        for r in summary:
            sid = r.get("safe_box_id")
            sb_total = r.get("sb_total")
            gl_total = r.get("gl_total")
            diff = r.get("diff")
            if sid is None:
                continue
            print(f"safe_box_id={sid} sb_total={sb_total} gl_total={gl_total} diff={diff}")

        if keyed:
            print("\n=== Keyed diffs (normalized) ===")
            for r in keyed[:200]:
                print(
                    f"{r.get('ref_type')}/{r.get('ref_id')}: sb={r.get('sb_signed')} gl={r.get('gl_signed')} diff={r.get('diff')}"
                )

        has_mismatch = any(abs(float(r.get("diff") or 0.0)) > 0.009 for r in summary if r.get("safe_box_id") is not None)
        if args.exit_nonzero and has_mismatch:
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
