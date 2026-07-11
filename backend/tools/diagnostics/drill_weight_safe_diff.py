"""
تفصيل الفروق في الخزائن الوزنية — Drill-Down
يعرض لكل خزينة:
  1. مجموع SBT مصنّف حسب ref_type
  2. مجموع GL (journal_entry_line) مصنّف حسب reference_type
  3. قائمة السطور المتعارضة (موجودة في SBT بدون GL مقابل والعكس)

Usage:
    python drill_weight_safe_diff.py --id 30
    python drill_weight_safe_diff.py --id 47
    python drill_weight_safe_diff.py --id 48
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


def _create_app() -> Flask:
    app = Flask(__name__)
    raw = os.getenv("DATABASE_URL", f"sqlite:///{os.path.join(BACKEND_DIR, 'app.db')}")
    if raw.startswith("postgres://"):
        raw = "postgresql://" + raw[len("postgres://"):]
    app.config["SQLALCHEMY_DATABASE_URI"] = raw
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)
    return app


def _print_section(title: str):
    print(f"\n{'─'*70}")
    print(f"  {title}")
    print(f"{'─'*70}")


def drill(safe_box_id: int):
    # ── معلومات الخزينة ──────────────────────────────────────────────────────
    info = db.session.execute(
        text("""
            SELECT sb.id, sb.name, sb.safe_type, sb.account_id,
                   a.account_number, a.name AS acc_name
            FROM safe_box sb
            JOIN account a ON a.id = sb.account_id
            WHERE sb.id = :sid
        """), {"sid": safe_box_id}
    ).fetchone()

    if not info:
        print(f"لم يتم العثور على خزينة id={safe_box_id}")
        return

    sb_id, sb_name, sb_type, acc_id, acc_num, acc_name = info
    print(f"\n{'='*70}")
    print(f"  Drill-Down: [{sb_id}] {sb_name}")
    print(f"  الحساب   : [{acc_num}] {acc_name}")
    print(f"{'='*70}")

    # ── 1. SBT حسب ref_type ──────────────────────────────────────────────────
    _print_section("1. SBT — مجموع الأوزان حسب ref_type")
    sbt_by_ref = db.session.execute(
        text("""
            SELECT
                COALESCE(ref_type, 'NULL') AS ref_type,
                COUNT(*) AS cnt,
                SUM(CASE WHEN direction='in' THEN weight_18k ELSE -weight_18k END) AS w18,
                SUM(CASE WHEN direction='in' THEN weight_21k ELSE -weight_21k END) AS w21,
                SUM(CASE WHEN direction='in' THEN weight_22k ELSE -weight_22k END) AS w22,
                SUM(CASE WHEN direction='in' THEN weight_24k ELSE -weight_24k END) AS w24
            FROM safe_box_transaction
            WHERE safe_box_id = :sid
              AND (weight_18k != 0 OR weight_21k != 0 OR weight_22k != 0 OR weight_24k != 0)
            GROUP BY 1
            ORDER BY ABS(SUM(CASE WHEN direction='in' THEN weight_21k ELSE -weight_21k END)) DESC
        """), {"sid": sb_id}
    ).fetchall()

    if not sbt_by_ref:
        print("  (لا توجد معاملات وزنية في SBT)")
    else:
        print(f"  {'ref_type':25s}  {'cnt':>5}  {'18k':>10}  {'21k':>10}  {'22k':>10}  {'24k':>10}")
        print(f"  {'':─<25s}  {'':─>5}  {'':─>10}  {'':─>10}  {'':─>10}  {'':─>10}")
        for row in sbt_by_ref:
            print(f"  {row[0]:25s}  {row[1]:>5}  {row[2]:>10.3f}  {row[3]:>10.3f}  {row[4]:>10.3f}  {row[5]:>10.3f}")

    # ── 2. GL حسب reference_type ─────────────────────────────────────────────
    _print_section("2. GL — مجموع الأوزان حسب reference_type")
    gl_by_ref = db.session.execute(
        text("""
            SELECT
                COALESCE(je.reference_type, 'NULL') AS ref_type,
                COUNT(DISTINCT je.id) AS je_cnt,
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
              AND (jl.debit_18k != 0 OR jl.credit_18k != 0
                OR jl.debit_21k != 0 OR jl.credit_21k != 0
                OR jl.debit_22k != 0 OR jl.credit_22k != 0
                OR jl.debit_24k != 0 OR jl.credit_24k != 0)
            GROUP BY 1
            ORDER BY ABS(SUM(COALESCE(jl.debit_21k,0) - COALESCE(jl.credit_21k,0))) DESC
        """), {"aid": acc_id}
    ).fetchall()

    if not gl_by_ref:
        print("  (لا توجد قيود وزنية في GL لهذا الحساب)")
    else:
        print(f"  {'ref_type':25s}  {'JEs':>5}  {'18k':>10}  {'21k':>10}  {'22k':>10}  {'24k':>10}")
        print(f"  {'':─<25s}  {'':─>5}  {'':─>10}  {'':─>10}  {'':─>10}  {'':─>10}")
        for row in gl_by_ref:
            print(f"  {row[0]:25s}  {row[1]:>5}  {row[2]:>10.3f}  {row[3]:>10.3f}  {row[4]:>10.3f}  {row[5]:>10.3f}")

    # ── 3. SBT بدون GL مقابل (orphan SBT) ──────────────────────────────────
    _print_section("3. SBT بدون قيد GL مقابل (orphan SBT rows)")
    orphan_sbt = db.session.execute(
        text("""
            SELECT
                sbt.id,
                COALESCE(sbt.ref_type,'NULL') AS ref_type,
                sbt.ref_id,
                sbt.direction,
                sbt.weight_18k, sbt.weight_21k, sbt.weight_22k, sbt.weight_24k,
                sbt.created_at
            FROM safe_box_transaction sbt
            WHERE sbt.safe_box_id = :sid
              AND (sbt.weight_18k != 0 OR sbt.weight_21k != 0
                OR sbt.weight_22k != 0 OR sbt.weight_24k != 0)
              AND NOT EXISTS (
                  SELECT 1
                  FROM journal_entry_line jl
                  JOIN journal_entry je ON je.id = jl.journal_entry_id
                  WHERE jl.account_id = :aid
                    AND COALESCE(jl.is_deleted, false) = false
                    AND COALESCE(je.is_deleted, false) = false
                    AND COALESCE(je.is_posted, true) = true
                    AND (
                        (LOWER(COALESCE(sbt.ref_type,'')) = 'journal_entry' AND je.id = sbt.ref_id)
                     OR (LOWER(COALESCE(sbt.ref_type,'')) LIKE 'invoice%'
                         AND je.reference_id = sbt.ref_id
                         AND LOWER(COALESCE(je.reference_type,'')) = 'invoice')
                     OR (LOWER(COALESCE(sbt.ref_type,'')) = 'invoice_payment'
                         AND je.reference_id = sbt.ref_id)
                     OR (LOWER(COALESCE(sbt.ref_type,'')) IN ('voucher','voucher_reversal')
                         AND je.reference_id = sbt.ref_id)
                    )
                    AND (jl.debit_18k != 0 OR jl.credit_18k != 0
                      OR jl.debit_21k != 0 OR jl.credit_21k != 0
                      OR jl.debit_22k != 0 OR jl.credit_22k != 0
                      OR jl.debit_24k != 0 OR jl.credit_24k != 0)
              )
            ORDER BY sbt.created_at DESC
            LIMIT 20
        """), {"sid": sb_id, "aid": acc_id}
    ).fetchall()

    if not orphan_sbt:
        print("  (لا توجد صفوف SBT بدون مقابل في GL)")
    else:
        print(f"  {'sbt_id':>6}  {'ref_type':20s}  {'ref_id':>8}  {'dir':4s}  {'18k':>8}  {'21k':>8}  {'22k':>8}  {'24k':>8}")
        for r in orphan_sbt:
            print(f"  {r[0]:>6}  {r[1]:20s}  {str(r[2] or ''):>8}  {r[3]:4s}  {r[4]:>8.3f}  {r[5]:>8.3f}  {r[6]:>8.3f}  {r[7]:>8.3f}")

    # ── 4. GL بدون SBT مقابل ────────────────────────────────────────────────
    _print_section("4. قيود GL بدون SBT مقابل (orphan GL lines)")
    orphan_gl = db.session.execute(
        text("""
            SELECT
                je.id AS je_id,
                COALESCE(je.reference_type,'NULL') AS ref_type,
                je.reference_id,
                je.date,
                jl.debit_18k, jl.credit_18k,
                jl.debit_21k, jl.credit_21k,
                jl.debit_24k, jl.credit_24k
            FROM journal_entry_line jl
            JOIN journal_entry je ON je.id = jl.journal_entry_id
            WHERE jl.account_id = :aid
              AND COALESCE(jl.is_deleted, false) = false
              AND COALESCE(je.is_deleted, false) = false
              AND COALESCE(je.is_draft, false) = false
              AND COALESCE(je.is_posted, true) = true
              AND (jl.debit_18k != 0 OR jl.credit_18k != 0
                OR jl.debit_21k != 0 OR jl.credit_21k != 0
                OR jl.debit_22k != 0 OR jl.credit_22k != 0
                OR jl.debit_24k != 0 OR jl.credit_24k != 0)
              AND NOT EXISTS (
                  SELECT 1 FROM safe_box_transaction sbt
                  WHERE sbt.safe_box_id = :sid
                    AND (sbt.weight_18k != 0 OR sbt.weight_21k != 0
                      OR sbt.weight_22k != 0 OR sbt.weight_24k != 0)
                    AND (
                        (LOWER(COALESCE(je.reference_type,'')) = 'journal_entry' AND sbt.ref_id = je.id)
                     OR (LOWER(COALESCE(je.reference_type,'')) = 'invoice'
                         AND sbt.ref_id = je.reference_id
                         AND LOWER(COALESCE(sbt.ref_type,'')) LIKE 'invoice%')
                     OR (LOWER(COALESCE(je.reference_type,'')) = 'invoice_payment'
                         AND sbt.ref_id = je.reference_id)
                     OR (LOWER(COALESCE(je.reference_type,'')) IN ('voucher','voucher_reversal')
                         AND sbt.ref_id = je.reference_id)
                    )
              )
            ORDER BY je.date DESC
            LIMIT 20
        """), {"sid": sb_id, "aid": acc_id}
    ).fetchall()

    if not orphan_gl:
        print("  (لا توجد قيود GL بدون SBT مقابل)")
    else:
        print(f"  {'je_id':>6}  {'ref_type':20s}  {'ref_id':>8}  {'date':12s}  "
              f"{'d18k':>8}  {'c18k':>8}  {'d21k':>8}  {'c21k':>8}  {'d24k':>8}  {'c24k':>8}")
        for r in orphan_gl:
            date_str = str(r[3])[:10] if r[3] else '—'
            print(f"  {r[0]:>6}  {r[1]:20s}  {str(r[2] or ''):>8}  {date_str:12s}  "
                  f"  {r[4] or 0:>6.2f}  {r[5] or 0:>6.2f}  {r[6] or 0:>6.2f}  "
                  f"  {r[7] or 0:>6.2f}  {r[8] or 0:>6.2f}  {r[9] or 0:>6.2f}")

    print(f"\n{'='*70}\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", type=int, required=True, help="معرف الخزينة")
    args = parser.parse_args()

    app = _create_app()
    with app.app_context():
        drill(args.id)


if __name__ == "__main__":
    main()
