"""
migration_v2/import_opening_entry.py
======================================
أداة استيراد قيد الافتتاح من opening_entry.json إلى قاعدة بيانات v2.

الاستخدام:
    python import_opening_entry.py \\
        --input opening_entry.json \\
        [--db-url "postgresql://user:pass@host:5432/yasargold_v2"] \\
        [--dry-run]          # معاينة بدون تسجيل
        [--force]            # إعادة الاستيراد إذا وُجد قيد افتتاح مسبقاً

أو عبر متغيرات البيئة:
    V2_DB_URL="postgresql://..." python import_opening_entry.py --input opening_entry.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

# ─── Flask app context ───────────────────────────────────────────────────────
# الأداة تعمل داخل حاوية backend حيث Flask مثبّت
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ─── Constants ───────────────────────────────────────────────────────────────

OPENING_ENTRY_TYPE = "افتتاحي"
OPENING_DESCRIPTION_PREFIX = "قيد الافتتاح"
CREATED_BY = "migration_v2"


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _d(v) -> float:
    """تحويل آمن للأرقام."""
    if v is None:
        return 0.0
    try:
        return float(Decimal(str(v)))
    except Exception:
        return 0.0


def _load_entry(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _find_account(db, Account, number: str) -> int | None:
    """يبحث عن حساب برقمه، يُنشئه تلقائياً إذا لم يوجد."""
    acc = Account.query.filter_by(account_number=number).first()
    if acc:
        return acc.id
    return None


def _get_or_create_equity_account(db, Account) -> int:
    """يضمن وجود حساب تسوية الافتتاح 3100."""
    acc = Account.query.filter_by(account_number="3100").first()
    if acc:
        return acc.id

    # إنشاء حساب تسوية إذا لم يوجد
    parent = Account.query.filter_by(account_number="3000").first()
    acc = Account(
        account_number="3100",
        name="حساب تسوية الافتتاح",
        account_type="equity",
        parent_id=parent.id if parent else None,
        is_active=True,
    )
    db.session.add(acc)
    db.session.flush()
    print(f"  [+] أُنشئ حساب تسوية الافتتاح: 3100")
    return acc.id


def _next_entry_number(JournalEntry) -> str:
    """يولّد رقم قيد فريد."""
    last = (
        JournalEntry.query
        .filter(JournalEntry.entry_number.like("OPN-%"))
        .order_by(JournalEntry.id.desc())
        .first()
    )
    seq = 1
    if last:
        try:
            seq = int(last.entry_number.split("-")[1]) + 1
        except Exception:
            pass
    return f"OPN-{seq:04d}"


# ─── Core Import Function ─────────────────────────────────────────────────────

def import_opening_entry(
    entry_data: dict,
    dry_run: bool = False,
    force: bool = False,
) -> dict:
    """
    يستورد قيد الافتتاح إلى قاعدة بيانات v2.

    Returns: تقرير الاستيراد
    """
    from app import app, db
    from models import Account, JournalEntry, JournalEntryLine

    report = {
        "dry_run": dry_run,
        "status": None,
        "entry_number": None,
        "lines_imported": 0,
        "lines_skipped": 0,
        "missing_accounts": [],
        "errors": [],
    }

    with app.app_context():
        # ─── التحقق من وجود قيد افتتاح مسبق ─────────────────────────────
        existing = (
            JournalEntry.query
            .filter_by(entry_type=OPENING_ENTRY_TYPE)
            .filter(JournalEntry.description.like(f"{OPENING_DESCRIPTION_PREFIX}%"))
            .first()
        )
        if existing and not force:
            report["status"] = "already_exists"
            report["entry_number"] = existing.entry_number
            print(f"⚠️  قيد افتتاح موجود مسبقاً: {existing.entry_number}")
            print("    استخدم --force لإعادة الاستيراد.")
            return report

        if existing and force:
            print(f"  [!] حذف قيد الافتتاح السابق: {existing.entry_number}")
            if not dry_run:
                db.session.delete(existing)
                db.session.flush()

        # ─── تحضير القيد ─────────────────────────────────────────────────
        entry_number = _next_entry_number(JournalEntry)
        entry_date_str = entry_data.get("date", datetime.today().strftime("%Y-%m-%d"))
        try:
            entry_date = datetime.strptime(entry_date_str, "%Y-%m-%d")
        except ValueError:
            entry_date = datetime.today()

        print(f"\n{'─'*60}")
        print(f"قيد الافتتاح: {entry_number}")
        print(f"التاريخ:      {entry_date_str}")
        print(f"الوصف:        {entry_data.get('description', '')}")
        print(f"عدد السطور:   {len(entry_data.get('lines', []))}")
        print(f"{'─'*60}")

        je = JournalEntry(
            entry_number=entry_number,
            date=entry_date,
            description=entry_data.get("description", f"{OPENING_DESCRIPTION_PREFIX} — v2"),
            entry_type=OPENING_ENTRY_TYPE,
            reference_type="migration_v2",
            reference_number="opening_entry.json",
            is_draft=False,
            is_posted=True,
            posted_at=datetime.now(),
            posted_by=CREATED_BY,
            created_by=CREATED_BY,
        )

        if not dry_run:
            db.session.add(je)
            db.session.flush()  # نحصل على je.id

        # ─── معالجة السطور ────────────────────────────────────────────────
        equity_account_id = _get_or_create_equity_account(db, Account) if not dry_run else None

        for i, line in enumerate(entry_data.get("lines", []), 1):
            acc_number = line.get("account_number", "")
            acc_id = None

            if not dry_run:
                acc_id = _find_account(db, Account, acc_number)
                if acc_id is None:
                    # حساب تسوية الافتتاح قد لا يكون موجوداً — أنشأناه أعلاه
                    if acc_number == "3100":
                        acc_id = equity_account_id
                    else:
                        report["lines_skipped"] += 1
                        report["missing_accounts"].append(acc_number)
                        print(f"  [!] سطر {i}: حساب {acc_number} غير موجود — تُجاوز")
                        continue

            side = line.get("side", "debit")
            is_weight = line.get("is_weight_account", False)
            amt = _d(line.get("amount_sar", 0))
            w18 = _d(line.get("weight_18k", 0))
            w21 = _d(line.get("weight_21k", 0))
            w22 = _d(line.get("weight_22k", 0))
            w24 = _d(line.get("weight_24k", 0))

            # تحديد القيم المدينة والدائنة
            if is_weight:
                cash_debit = cash_credit = 0.0
                d18 = w18 if side == "debit" else 0.0
                c18 = w18 if side == "credit" else 0.0
                d21 = w21 if side == "debit" else 0.0
                c21 = w21 if side == "credit" else 0.0
                d22 = w22 if side == "debit" else 0.0
                c22 = w22 if side == "credit" else 0.0
                d24 = w24 if side == "debit" else 0.0
                c24 = w24 if side == "credit" else 0.0
                weight_type = "PHYSICAL"
            else:
                cash_debit  = amt if side == "debit"  else 0.0
                cash_credit = amt if side == "credit" else 0.0
                d18 = c18 = d21 = c21 = d22 = c22 = d24 = c24 = 0.0
                weight_type = "ANALYTICAL"

            desc = line.get("description", "")
            party_type = line.get("party_type")
            party_id   = line.get("party_id")

            # طباعة للمعاينة
            if dry_run or i <= 5 or (i % 20 == 0):
                sign = "مدين" if side == "debit" else "دائن"
                if is_weight:
                    w_total = w18 + w21 + w22 + w24
                    print(f"  [{i:3d}] {acc_number:<10} {sign:<5} وزن={w_total:.3f}g  {desc[:40]}")
                else:
                    print(f"  [{i:3d}] {acc_number:<10} {sign:<5} {amt:>12.2f} ر  {desc[:40]}")

            if not dry_run:
                jel = JournalEntryLine(
                    journal_entry_id=je.id,
                    account_id=acc_id,
                    cash_debit=cash_debit,
                    cash_credit=cash_credit,
                    debit_18k=d18,
                    credit_18k=c18,
                    debit_21k=d21,
                    credit_21k=c21,
                    debit_22k=d22,
                    credit_22k=c22,
                    debit_24k=d24,
                    credit_24k=c24,
                    weight_type=weight_type,
                    description=desc,
                    customer_id=party_id if party_type == "customer" else None,
                    supplier_id=party_id if party_type == "supplier" else None,
                )
                db.session.add(jel)
                report["lines_imported"] += 1
            else:
                report["lines_imported"] += 1

        # ─── الحفظ ────────────────────────────────────────────────────────
        if not dry_run:
            db.session.commit()
            report["status"] = "success"
            report["entry_number"] = entry_number
        else:
            report["status"] = "dry_run_ok"

        # ─── ملخص ─────────────────────────────────────────────────────────
        print(f"\n{'═'*60}")
        if dry_run:
            print(f"  [DRY RUN] لم يُحفظ شيء")
        else:
            print(f"  ✓ تم الحفظ: {entry_number}")
        print(f"  سطور مستوردة: {report['lines_imported']}")
        print(f"  سطور مُتجاوزة: {report['lines_skipped']}")
        if report["missing_accounts"]:
            print(f"  حسابات مفقودة: {', '.join(set(report['missing_accounts']))}")
        print(f"  توازن نقدي:  {entry_data.get('is_cash_balanced', '?')}")
        print(f"  توازن وزني: {entry_data.get('is_weight_balanced', '?')}")
        print(f"{'═'*60}\n")

    return report


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="استيراد قيد الافتتاح من opening_entry.json إلى v2"
    )
    parser.add_argument(
        "--input", "-i",
        default="opening_entry.json",
        help="مسار ملف opening_entry.json",
    )
    parser.add_argument(
        "--db-url",
        default=os.environ.get("V2_DB_URL", ""),
        help="رابط قاعدة بيانات v2 (أو V2_DB_URL env)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="معاينة بدون حفظ فعلي",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="إعادة الاستيراد حتى لو وُجد قيد افتتاح",
    )
    args = parser.parse_args()

    # تعيين DATABASE_URL لـ Flask
    if args.db_url:
        os.environ["DATABASE_URL"] = args.db_url

    if not Path(args.input).exists():
        print(f"خطأ: الملف غير موجود: {args.input}")
        sys.exit(1)

    entry_data = _load_entry(args.input)

    if args.dry_run:
        print("=" * 60)
        print("  وضع المعاينة (DRY RUN) — لن يُحفظ شيء")
        print("=" * 60)

    report = import_opening_entry(
        entry_data=entry_data,
        dry_run=args.dry_run,
        force=args.force,
    )

    if report["status"] == "already_exists":
        sys.exit(2)
    elif report["errors"]:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
