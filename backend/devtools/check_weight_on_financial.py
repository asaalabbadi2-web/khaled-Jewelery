"""
فحص شامل دقيق: هل يوجد قيد وزني مكتوب على حساب مالي (غير 7xxxx)؟
يفحص عمودي debit_weight/credit_weight (الوزن الموحّد) وعمودي debit_21k/credit_21k
وجميع عيارات. السبب: debit_weight يُكتب فقط لحسابات 7xxxx، لكن debit_21k وغيره
يُكتب لأي حساب عند استدعاء create_dual_journal_entry.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as flask_app
from models import db, JournalEntryLine, JournalEntry, Account
from sqlalchemy import or_, and_

PASS = "\u2705"
FAIL = "\u274c"

with flask_app.app.app_context():
    # فحص 1: سطور لها debit_weight أو credit_weight على حسابات غير 7xxx
    q1 = (
        db.session.query(JournalEntryLine, JournalEntry, Account)
        .join(JournalEntry, JournalEntryLine.journal_entry_id == JournalEntry.id)
        .join(Account, JournalEntryLine.account_id == Account.id)
        .filter(
            or_(JournalEntryLine.debit_weight > 0, JournalEntryLine.credit_weight > 0)
        )
        .all()
    )

    # فحص 2: سطور لها أي قيمة في أعمدة العيارات على حسابات غير 7xxx  ← الفحص الحقيقي
    q2 = (
        db.session.query(JournalEntryLine, JournalEntry, Account)
        .join(JournalEntry, JournalEntryLine.journal_entry_id == JournalEntry.id)
        .join(Account, JournalEntryLine.account_id == Account.id)
        .filter(
            or_(
                JournalEntryLine.debit_18k > 0, JournalEntryLine.credit_18k > 0,
                JournalEntryLine.debit_21k > 0, JournalEntryLine.credit_21k > 0,
                JournalEntryLine.debit_22k > 0, JournalEntryLine.credit_22k > 0,
                JournalEntryLine.debit_24k > 0, JournalEntryLine.credit_24k > 0,
            )
        )
        .all()
    )

    # تصنيف النتائج
    def classify(rows):
        bad = []
        by_type = {}
        for jel, je, acc in rows:
            acc_num = acc.account_number or ""
            is_weight = acc_num.startswith("7")
            ref_type = je.reference_type or "unknown"
            by_type.setdefault(ref_type, {"total": 0, "bad": 0})
            by_type[ref_type]["total"] += 1
            if not is_weight:
                bad.append((jel.id, je.id, ref_type, je.reference_id,
                             acc_num, acc.name or "",
                             float(jel.debit_21k or 0), float(jel.credit_21k or 0),
                             float(jel.debit_18k or 0), float(jel.credit_18k or 0),
                             float(jel.debit_weight or 0), float(jel.credit_weight or 0)))
                by_type[ref_type]["bad"] += 1
        return bad, by_type

    bad1, by_type1 = classify(q1)
    bad2, by_type2 = classify(q2)

    print("\n" + "="*70)
    print("فحص A: عمودا debit_weight/credit_weight (الوزن الموحّد المحسوب)")
    print("="*70)
    print(f"اجمالي سطور وزنية (debit_weight/credit_weight): {len(q1)}")
    for ref_type, s in sorted(by_type1.items()):
        icon = PASS if s["bad"] == 0 else FAIL
        print(f"  {icon}  {ref_type:<35}  total={s['total']:>4}  على_مالي={s['bad']:>4}")
    if not bad1:
        print(f"\n{PASS}  لا يوجد debit_weight/credit_weight على حسابات مالية")
    else:
        print(f"\n{FAIL}  {len(bad1)} سطر بـ debit_weight على حساب مالي!")

    print("\n" + "="*70)
    print("فحص B: أعمدة debit_21k/credit_21k/18k/22k/24k — الفحص الكامل والحقيقي")
    print("="*70)
    print(f"اجمالي سطور لها قيمة عيار (debit_Xk > 0): {len(q2)}")
    for ref_type, s in sorted(by_type2.items()):
        icon = PASS if s["bad"] == 0 else FAIL
        print(f"  {icon}  {ref_type:<35}  total={s['total']:>4}  على_مالي={s['bad']:>4}")

    if not bad2:
        print(f"\n{PASS}  لا يوجد أي قيمة عيار على حساب مالي في كامل قاعدة البيانات")
        print(f"{PASS}  المشكلة ليست منتشرة — الإصلاح شامل لجميع الأنواع")
    else:
        print(f"\n{FAIL}  وجد {len(bad2)} سطر يحتوي قيمة عيار على حساب مالي:")
        shown = 0
        prev_type = None
        for row in bad2:
            jel_id, je_id, ref_type, ref_id, acc_num, acc_name, d21, c21, d18, c18, dw, cw = row
            if ref_type != prev_type:
                print(f"\n  [{ref_type}]")
                prev_type = ref_type
            print(
                f"    line={jel_id:<6}  je={je_id:<6}  ref_id={ref_id!s:<8}"
                f"  acc={acc_num:<12} ({acc_name[:28]})  "
                f"d21={d21:.3f} c21={c21:.3f}  d18={d18:.3f} c18={c18:.3f}  "
                f"dw(main)={dw:.4f} cw(main)={cw:.4f}"
            )
            shown += 1
            if shown >= 40:
                print(f"  ... و {len(bad2)-40} سطر اضافي")
                break

    # ملخص اجمالي
    print("\n" + "="*70)
    print("الخلاصة:")
    if not bad2:
        print(f"  {PASS}  جميع القيود الوزنية سليمة على الحسابات الصحيحة (7xxxx)")
        print(f"  {PASS}  الإصلاح (apply_je_to_db + _resolve_weight_account_id) يغطي كل المسارات")
    else:
        by_bad_type = {}
        for row in bad2:
            by_bad_type.setdefault(row[2], 0)
            by_bad_type[row[2]] += 1
        print(f"  {FAIL}  الأنواع المتأثرة:")
        for t, cnt in sorted(by_bad_type.items()):
            print(f"       [{t}]: {cnt} سطر")

sys.exit(1 if bad2 else 0)

