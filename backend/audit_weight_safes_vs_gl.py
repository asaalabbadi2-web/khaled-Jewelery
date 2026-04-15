"""
مطابقة الخزائن الوزنية مع دفتر الأستاذ (GL)
Weight Safe Boxes vs General Ledger Reconciliation

يقارن هذا السكريبت رصيد كل خزينة ذهبية (safe_box_transaction) مع
المجموع المقابل في journal_entry_line للحساب المرتبط.

Usage:
    python audit_weight_safes_vs_gl.py            # كل الخزائن الذهبية
    python audit_weight_safes_vs_gl.py --id 5     # خزينة بعينها
    python audit_weight_safes_vs_gl.py --diff-only # الخزائن التي بها فروق فقط
"""

from __future__ import annotations

import argparse
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from flask import Flask
from sqlalchemy import text

from models import db

KARATS = [18, 21, 22, 24]
TOL = 0.001  # tolerance جرام


def _create_app() -> Flask:
    app = Flask(__name__)
    raw = os.getenv("DATABASE_URL", f"sqlite:///{os.path.join(BACKEND_DIR, 'app.db')}")
    if raw.startswith("postgres://"):
        raw = "postgresql://" + raw[len("postgres://"):]
    app.config["SQLALCHEMY_DATABASE_URI"] = raw
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)
    return app


def _sbt_weight(safe_box_id: int) -> dict[int, float]:
    """رصيد الأوزان من safe_box_transaction لكل عيار."""
    rows = db.session.execute(
        text("""
            SELECT
                SUM(CASE WHEN direction='in' THEN weight_18k ELSE -weight_18k END) AS w18,
                SUM(CASE WHEN direction='in' THEN weight_21k ELSE -weight_21k END) AS w21,
                SUM(CASE WHEN direction='in' THEN weight_22k ELSE -weight_22k END) AS w22,
                SUM(CASE WHEN direction='in' THEN weight_24k ELSE -weight_24k END) AS w24
            FROM safe_box_transaction
            WHERE safe_box_id = :sid
        """),
        {"sid": safe_box_id},
    ).fetchone()
    return {
        18: float(rows[0] or 0),
        21: float(rows[1] or 0),
        22: float(rows[2] or 0),
        24: float(rows[3] or 0),
    }


def _gl_weight(account_id: int) -> dict[int, float]:
    """رصيد الأوزان من journal_entry_line للحساب الوزني."""
    rows = db.session.execute(
        text("""
            SELECT
                SUM(COALESCE(jl.debit_18k,0) - COALESCE(jl.credit_18k,0)) AS w18,
                SUM(COALESCE(jl.debit_21k,0) - COALESCE(jl.credit_21k,0)) AS w21,
                SUM(COALESCE(jl.debit_22k,0) - COALESCE(jl.credit_22k,0)) AS w22,
                SUM(COALESCE(jl.debit_24k,0) - COALESCE(jl.credit_24k,0)) AS w24
            FROM journal_entry_line jl
            JOIN journal_entry je ON je.id = jl.journal_entry_id
            WHERE jl.account_id = :aid
              AND COALESCE(jl.is_deleted, false) = false
              AND COALESCE(je.is_deleted, false) = false
              AND COALESCE(je.is_draft,  false) = false
              AND COALESCE(je.is_posted, true)  = true
        """),
        {"aid": account_id},
    ).fetchone()
    return {
        18: float(rows[0] or 0),
        21: float(rows[1] or 0),
        22: float(rows[2] or 0),
        24: float(rows[3] or 0),
    }


def _run(*, safe_box_id: int | None, diff_only: bool) -> int:
    """يُشغّل المطابقة ويعيد عدد الخزائن التي بها فروق."""

    where = ""
    params: dict = {}
    if safe_box_id is not None:
        where = "WHERE sb.id = :sid"
        params["sid"] = int(safe_box_id)
    else:
        where = "WHERE sb.safe_type = 'gold'"

    safes = db.session.execute(
        text(f"""
            SELECT sb.id, sb.name, sb.account_id, a.account_number, a.name AS acc_name
            FROM safe_box sb
            JOIN account a ON a.id = sb.account_id
            {where}
            ORDER BY sb.id
        """),
        params,
    ).fetchall()

    if not safes:
        print("لم يتم العثور على خزائن ذهبية.")
        return 0

    print(f"\nDB: {db.engine.url}")
    print(f"{'='*72}")
    print(f"  مطابقة الخزائن الوزنية مع دفتر الأستاذ (GL)")
    print(f"{'='*72}")

    diff_count = 0

    for row in safes:
        sb_id, sb_name, acc_id, acc_num, acc_name = row

        sbt = _sbt_weight(sb_id)
        gl  = _gl_weight(acc_id)

        diffs = {k: round(sbt[k] - gl[k], 6) for k in KARATS}
        has_diff = any(abs(d) > TOL for d in diffs.values())

        if diff_only and not has_diff:
            continue

        status = "❌ فرق" if has_diff else "✅ متطابق"
        print(f"\n{'─'*72}")
        print(f"  الخزينة  : [{sb_id}] {sb_name}")
        print(f"  الحساب   : [{acc_num}] {acc_name}")
        print(f"  الحالة   : {status}")
        print(f"  {'العيار':>8}  {'خزينة (SBT)':>14}  {'GL':>14}  {'فرق':>12}")
        print(f"  {'':─>8}  {'':─>14}  {'':─>14}  {'':─>12}")

        for k in KARATS:
            diff_str = f"{diffs[k]:+.4f}" if abs(diffs[k]) > TOL else "  —"
            flag = " ⚠️" if abs(diffs[k]) > TOL else ""
            print(f"  {k:>6}k   {sbt[k]:>14.4f}  {gl[k]:>14.4f}  {diff_str:>12}{flag}")

        if has_diff:
            diff_count += 1

    print(f"\n{'='*72}")
    if diff_count:
        print(f"⚠️  {diff_count} خزينة/خزائن بها فروق من أصل {len(safes)}")
    else:
        print(f"✅ جميع الخزائن ({len(safes)}) متطابقة مع GL")
    print(f"{'='*72}\n")

    return diff_count


def main():
    parser = argparse.ArgumentParser(description="مطابقة الخزائن الوزنية مع GL")
    parser.add_argument("--id", type=int, dest="safe_box_id", default=None,
                        help="معرف خزينة محددة (اختياري)")
    parser.add_argument("--diff-only", action="store_true",
                        help="اعرض الخزائن التي بها فروق فقط")
    parser.add_argument("--exit-nonzero", action="store_true",
                        help="أعد exit code 1 إذا وُجدت فروق (مفيد في CI)")
    args = parser.parse_args()

    app = _create_app()
    with app.app_context():
        diffs = _run(safe_box_id=args.safe_box_id, diff_only=args.diff_only)

    if args.exit_nonzero and diffs:
        sys.exit(1)


if __name__ == "__main__":
    main()
