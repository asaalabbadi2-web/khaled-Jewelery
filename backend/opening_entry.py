#!/usr/bin/env python3
"""
opening_entry.py — قيد افتتاحي لأرصدة الذهب الوزنية فقط

النطاق: حسابات الذهب الوزنية المتأثرة بالتحول v1→v2:
  • صناديق الذهب  (71300، 71310000)
  • عهد الموظفين  (713100xxx)
  • حسابات موردين وزنية (72100xxx) — ذهب تحت التصرف لدى الأطراف الخارجية
  موازنة: حساب 732 (أرباح/خسائر محتجزة وزني)

حسابات خارج النطاق (تُبنى من المعاملات الجارية):
  • ذمم العملاء / الموردين المالية
  • الصناديق النقدية والبنوك
  • أرصدة العملاء الوزنية

الاستخدام:
    cd backend
    source venv/bin/activate
    python opening_entry.py --dry-run    # معاينة بدون تطبيق
    python opening_entry.py --apply      # تطبيق فعلي
"""

import json
import os
import sys
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime

# ─── إعدادات ───────────────────────────────────────────────────────
DRY_RUN       = '--apply' not in sys.argv
SNAPSHOT_PATH = os.path.join(os.path.dirname(__file__), '..', 'balance_snapshot.json')

CUTOVER_DATE          = '2026-04-02'
WEIGHT_EQUITY_ACCOUNT = '732'   # أرباح/خسائر محتجزة وزني — موازنة الوزن

# بادئات حسابات الموردين الوزنية المراد تضمينها
SUPPLIER_WEIGHT_PREFIXES = ('72100',)
# بادئات عهد الموظفين
EMPLOYEE_VAULT_PREFIX    = '7131000'
# حسابات مخزون ذهب جديد/كسر الرئيسية
MAIN_GOLD_SAFES = {'71300', '71310000'}
# ────────────────────────────────────────────────────────────────────

def _d(v, places=3):
    return Decimal(str(v or 0)).quantize(Decimal('0.001'), rounding=ROUND_HALF_UP)


def main():
    with open(SNAPSHOT_PATH, encoding='utf-8') as f:
        snap = json.load(f)

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import app as _app
    flask_app = _app.app

    with flask_app.app_context():
        from models import db, Account, JournalEntry
        from dual_system_helpers import create_dual_journal_entry

        _cache = {}
        def get_acct(number):
            k = str(number)
            if k not in _cache:
                _cache[k] = Account.query.filter_by(account_number=k).first()
            return _cache[k]

        lines   = []   # قائمة سطور القيد
        missing = []   # حسابات غير موجودة في v2

        def add(acct_num, *, w18d=0, w18c=0, w21d=0, w21c=0,
                w22d=0, w22c=0, w24d=0, w24c=0, desc=''):
            acc = get_acct(acct_num)
            if not acc:
                missing.append(f"{acct_num}  ←  {desc}")
                return
            vals = (w18d, w18c, w21d, w21c, w22d, w22c, w24d, w24c)
            if all(float(v) == 0 for v in vals):
                return
            lines.append(dict(
                account_number=acct_num, account_id=acc.id,
                w18d=float(w18d), w18c=float(w18c),
                w21d=float(w21d), w21c=float(w21c),
                w22d=float(w22d), w22c=float(w22c),
                w24d=float(w24d), w24c=float(w24c),
                desc=desc,
            ))

        # ══════════════════════════════════════════════════════════════
        # 1. صناديق الذهب الرئيسية + عهد الموظفين
        # ══════════════════════════════════════════════════════════════
        for sb in snap['safe_boxes']:
            if sb['safe_type'] != 'gold':
                continue
            acct_num = str(sb['account_number'])
            is_main   = acct_num in MAIN_GOLD_SAFES
            is_vault  = acct_num.startswith(EMPLOYEE_VAULT_PREFIX)
            if not (is_main or is_vault):
                continue
            w18 = _d(sb['weight_18k'])
            w21 = _d(sb['weight_21k'])
            w22 = _d(sb['weight_22k'])
            w24 = _d(sb['weight_24k'])
            add(acct_num,
                w18d=float(w18) if w18 > 0 else 0, w18c=float(-w18) if w18 < 0 else 0,
                w21d=float(w21) if w21 > 0 else 0, w21c=float(-w21) if w21 < 0 else 0,
                w22d=float(w22) if w22 > 0 else 0, w22c=float(-w22) if w22 < 0 else 0,
                w24d=float(w24) if w24 > 0 else 0, w24c=float(-w24) if w24 < 0 else 0,
                desc=f"رصيد افتتاحي وزن — {sb['name']}")

        # ══════════════════════════════════════════════════════════════
        # 2. حسابات الموردين الوزنية (ذهب تحت التصرف لدى الأطراف الخارجية)
        # ══════════════════════════════════════════════════════════════
        for s in snap['suppliers']:
            wn = str(s['weight_account_number'])
            if not any(wn.startswith(p) for p in SUPPLIER_WEIGHT_PREFIXES):
                continue
            w18 = _d(s['net_weight_18k'])
            w21 = _d(s['net_weight_21k'])
            w22 = _d(s['net_weight_22k'])
            w24 = _d(s['net_weight_24k'])
            add(wn,
                w18d=float(w18) if w18 > 0 else 0, w18c=float(-w18) if w18 < 0 else 0,
                w21d=float(w21) if w21 > 0 else 0, w21c=float(-w21) if w21 < 0 else 0,
                w22d=float(w22) if w22 > 0 else 0, w22c=float(-w22) if w22 < 0 else 0,
                w24d=float(w24) if w24 > 0 else 0, w24c=float(-w24) if w24 < 0 else 0,
                desc=f"رصيد افتتاحي وزن مورد — {s['name']}")

        # ══════════════════════════════════════════════════════════════
        # حساب فوارق الوزن وإضافة سطر الموازنة (حساب 732)
        # ══════════════════════════════════════════════════════════════
        def _wdiff(d_key, c_key):
            return round(sum(l[d_key] for l in lines) - sum(l[c_key] for l in lines), 3)

        w18_diff = _wdiff('w18d', 'w18c')
        w21_diff = _wdiff('w21d', 'w21c')
        w22_diff = _wdiff('w22d', 'w22c')
        w24_diff = _wdiff('w24d', 'w24c')

        # موازنة وزن كل عيار عبر حساب 732
        # الفارق الموجب (مدين أكثر) → نضيف دائن بـ 732
        # الفارق السالب (دائن أكثر) → نضيف مدين بـ 732
        add(WEIGHT_EQUITY_ACCOUNT,
            w18d=0 if w18_diff >= 0 else abs(w18_diff),
            w18c=w18_diff if w18_diff > 0 else 0,
            w21d=0 if w21_diff >= 0 else abs(w21_diff),
            w21c=w21_diff if w21_diff > 0 else 0,
            w22d=0 if w22_diff >= 0 else abs(w22_diff),
            w22c=w22_diff if w22_diff > 0 else 0,
            w24d=0 if w24_diff >= 0 else abs(w24_diff),
            w24c=w24_diff if w24_diff > 0 else 0,
            desc='موازنة وزنية افتتاحية — أرباح/خسائر محتجزة وزني')

        # ══════════════════════════════════════════════════════════════
        # طباعة التقرير
        # ══════════════════════════════════════════════════════════════
        SEP = '═' * 70

        print(f'\n{SEP}')
        print(f'  قيد افتتاحي — أرصدة الذهب الوزنية المتأثرة بالتحول   |   {CUTOVER_DATE}')
        print(SEP)

        # ─ حسابات مفقودة
        if missing:
            print(f'\n⚠️  حسابات غير موجودة في v2 ({len(missing)}) — يجب إنشاؤها أولاً:')
            for m in missing:
                print(f'   ✗  {m}')

        # ─ تفاصيل السطور (وزن فقط)
        print(f'\n{"الحساب":15}  {"18k (صافي)":>10}  {"21k (صافي)":>10}  {"22k":>8}  {"24k":>8}  الوصف')
        print('─' * 90)
        for l in lines:
            w18n = round(l['w18d'] - l['w18c'], 3)
            w21n = round(l['w21d'] - l['w21c'], 3)
            w22n = round(l['w22d'] - l['w22c'], 3)
            w24n = round(l['w24d'] - l['w24c'], 3)
            w18s = f"{w18n:>10.3f}" if w18n else ' ' * 10
            w21s = f"{w21n:>10.3f}" if w21n else ' ' * 10
            w22s = f"{w22n:>8.3f}"  if w22n else ' ' * 8
            w24s = f"{w24n:>8.3f}"  if w24n else ' ' * 8
            print(f'{l["account_number"]:15}  {w18s}  {w21s}  {w22s}  {w24s}  {l["desc"][:50]}')

        # ─ ملخص
        final_w18 = round(sum(l['w18d'] - l['w18c'] for l in lines), 3)
        final_w21 = round(sum(l['w21d'] - l['w21c'] for l in lines), 3)
        final_w22 = round(sum(l['w22d'] - l['w22c'] for l in lines), 3)
        final_w24 = round(sum(l['w24d'] - l['w24c'] for l in lines), 3)

        print('\n' + SEP)
        print(f'  فارق وزن 18k  :  {final_w18:>14,.3f} g    {"✅ متوازن" if abs(final_w18)<0.001 else "❌ غير متوازن"}')
        print(f'  فارق وزن 21k  :  {final_w21:>14,.3f} g    {"✅ متوازن" if abs(final_w21)<0.001 else "❌ غير متوازن"}')
        print(f'  فارق وزن 22k  :  {final_w22:>14,.3f} g    {"✅ متوازن" if abs(final_w22)<0.001 else "❌ غير متوازن"}')
        print(f'  فارق وزن 24k  :  {final_w24:>14,.3f} g    {"✅ متوازن" if abs(final_w24)<0.001 else "❌ غير متوازن"}')
        print(f'  عدد السطور    :  {len(lines)}')
        print(SEP)
        print(f'\n  ملاحظة: حسابات العملاء والموردين المالية والخزن النقدية')
        print(f'  خارج النطاق — تُبنى من المعاملات الجارية في v2.')

        if DRY_RUN:
            print('\n🔍  DRY RUN — لم يُطبَّق شيء. أعد التشغيل بـ --apply للتطبيق الفعلي.\n')
            return

        if missing:
            print('\n❌  يوجد حسابات مفقودة — أنشئها أولاً ثم أعد التشغيل.')
            sys.exit(1)

        # ══════════════════════════════════════════════════════════════
        # تطبيق القيد
        # ══════════════════════════════════════════════════════════════
        # منع التكرار
        existing = JournalEntry.query.filter_by(
            reference_type='opening',
        ).filter(JournalEntry.description.contains('قيد افتتاحي — التحول')).first()
        if existing:
            print(f'\n⚠️  القيد الافتتاحي موجود مسبقاً (JE id={existing.id}). لا شيء جديد.')
            return

        je = JournalEntry(
            date=datetime.strptime(CUTOVER_DATE, '%Y-%m-%d'),
            description='قيد افتتاحي — التحول من v1 إلى v2 (أرصدة ذهب وزنية)',
            reference_type='opening',
            reference_id=None,
            is_posted=True,
            posted_at=datetime.utcnow(),
            posted_by='system_migration',
        )
        db.session.add(je)
        db.session.flush()

        for l in lines:
            create_dual_journal_entry(
                journal_entry_id=je.id,
                account_id=l['account_id'],
                cash_debit=0,
                cash_credit=0,
                weight_18k_debit=l['w18d'],  weight_18k_credit=l['w18c'],
                weight_21k_debit=l['w21d'],  weight_21k_credit=l['w21c'],
                weight_22k_debit=l['w22d'],  weight_22k_credit=l['w22c'],
                weight_24k_debit=l['w24d'],  weight_24k_credit=l['w24c'],
                description=l['desc'],
                apply_golden_rule=False,
            )

        db.session.commit()
        print(f'\n✅  تم إنشاء القيد الافتتاحي — JE id={je.id}\n')


if __name__ == '__main__':
    main()
