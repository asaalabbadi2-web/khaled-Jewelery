#!/usr/bin/env python3
"""
create_missing_accounts.py — إنشاء الحسابات المفقودة في v2 من snapshot الإنتاج

يقرأ balance_snapshot.json ويُنشئ:
  - حسابات العملاء المالية (1200xxx) + الوزنية (71200xxx)
  - حسابات الموردين المالية (2100xxx) + الوزنية (72100xxx)
  - حسابات عهدة الموظفين (713100xxx) الوزنية

الاستخدام:
    cd backend
    source venv/bin/activate
    python create_missing_accounts.py --dry-run   # معاينة فقط
    python create_missing_accounts.py --apply      # تطبيق فعلي
"""

import json
import os
import sys

DRY_RUN       = '--apply' not in sys.argv
SNAPSHOT_PATH = os.path.join(os.path.dirname(__file__), '..', 'balance_snapshot.json')

# ─── ثوابت الحسابات الأم ────────────────────────────────────────────
PARENT_CUSTOMER_FINANCIAL = '1200'      # عملاء مجوهرات خالد
PARENT_CUSTOMER_WEIGHT    = '71200'     # عملاء مجوهرات خالد وزني
PARENT_SUPPLIER_FINANCIAL = '2100'      # حسابات موردو الذهب المشغول
PARENT_SUPPLIER_WEIGHT    = '72100'     # حسابات الموردين وزني
PARENT_EMPLOYEE_VAULT     = '71310001'  # حساب عهدة ذهب الموظفين وزني
# ────────────────────────────────────────────────────────────────────


def main():
    with open(SNAPSHOT_PATH, encoding='utf-8') as f:
        snap = json.load(f)

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import app as _app
    flask_app = _app.app

    with flask_app.app_context():
        from models import db, Account
        from account_pair_service import link_accounts

        def get_by_number(num):
            return Account.query.filter_by(account_number=str(num)).first()

        def get_parent_id(num):
            acc = get_by_number(num)
            if not acc:
                print(f'  ⚠️  حساب أم غير موجود: {num}')
                return None
            return acc.id

        to_create = []   # قائمة الحسابات المطلوب إنشاؤها

        def plan(acct_num, name, acct_type, transaction_type,
                 parent_number, tracks_weight=False, memo_number=None, note=''):
            """أضف حساباً للقائمة إذا لم يكن موجوداً."""
            existing = get_by_number(acct_num)
            if existing:
                return  # موجود، لا شيء
            to_create.append(dict(
                account_number=str(acct_num),
                name=name,
                type=acct_type,
                transaction_type=transaction_type,
                parent_number=str(parent_number),
                tracks_weight=tracks_weight,
                memo_number=str(memo_number) if memo_number else None,
                note=note,
            ))

        # ══════════════════════════════════════════════════════════════
        # 1. العملاء
        # ══════════════════════════════════════════════════════════════
        for c in snap['customers']:
            fn = c['financial_account_number']   # 1200xxx
            wn = c['weight_account_number']       # 71200xxx
            name = c['name'] or 'عميل'

            plan(fn, name,
                 'Asset', 'cash',
                 PARENT_CUSTOMER_FINANCIAL,
                 tracks_weight=False,
                 memo_number=wn,
                 note=f'ذمم عميل — {name}')

            plan(wn, f'أرصدة ذهب العملاء - {name}',
                 'Asset', 'gold',
                 PARENT_CUSTOMER_WEIGHT,
                 tracks_weight=True,
                 memo_number=fn,
                 note=f'وزن عميل — {name}')

        # ══════════════════════════════════════════════════════════════
        # 2. الموردون
        # ══════════════════════════════════════════════════════════════
        for s in snap['suppliers']:
            fn = s['financial_account_number']   # 2100xxx
            wn = s['weight_account_number']       # 72100xxx
            name = s['name'] or 'مورد'

            plan(fn, name,
                 'Liability', 'cash',
                 PARENT_SUPPLIER_FINANCIAL,
                 tracks_weight=False,
                 memo_number=wn,
                 note=f'مورد مالي — {name}')

            plan(wn, f'موردو ذهب مشغول وزني - {name}',
                 'Liability', 'gold',
                 PARENT_SUPPLIER_WEIGHT,
                 tracks_weight=True,
                 memo_number=fn,
                 note=f'وزن مورد — {name}')

        # ══════════════════════════════════════════════════════════════
        # 3. صناديق الذهب — أرصدة صندوق الكسر حسابات مفقودة
        # ══════════════════════════════════════════════════════════════
        # حسابنا بشركة الجنيه العربي: 72100001 (ظهر في safe_boxes كـ gold safe)
        # يُعالَج من قسم الموردين أعلاه لأن المورد "شركة الجنية العربي" → 72100001

        # ══════════════════════════════════════════════════════════════
        # 4. عهدة الموظفين
        # ══════════════════════════════════════════════════════════════
        for sb in snap['safe_boxes']:
            if sb.get('safe_type') != 'gold':
                continue
            acct_num = sb['account_number']
            # حسابات عهدة الموظفين تبدأ بـ 71310001
            if not str(acct_num).startswith('7131000'):
                continue
            name = sb['name']
            plan(acct_num, name,
                 'asset', 'gold',
                 PARENT_EMPLOYEE_VAULT,
                 tracks_weight=True,
                 note=f'عهدة وزنية — {name}')

        # ══════════════════════════════════════════════════════════════
        # طباعة التقرير
        # ══════════════════════════════════════════════════════════════
        SEP = '═' * 60
        print(f'\n{SEP}')
        print(f'  إنشاء الحسابات المفقودة   |   {len(to_create)} حساب')
        print(SEP)

        if not to_create:
            print('\n✅  لا توجد حسابات مفقودة — جميع الحسابات موجودة في v2.\n')
            return

        for ac in to_create:
            print(f'  + {ac["account_number"]:15}  {ac["name"][:40]:40}  '
                  f'{ac["type"]:12}  {ac["transaction_type"]:5}  '
                  f'memo={ac["memo_number"] or "-"}')

        print(f'\n  الإجمالي: {len(to_create)} حساب جديد')

        if DRY_RUN:
            print('\n🔍  DRY RUN — لم يُنشأ شيء. أعد التشغيل بـ --apply للتطبيق الفعلي.\n')
            return

        # ══════════════════════════════════════════════════════════════
        # إنشاء الحسابات
        # ══════════════════════════════════════════════════════════════
        # المرحلة 1: إنشاء الحسابات بدون ربط memo_account_id
        created = {}   # account_number → Account object
        parent_cache = {}

        def _parent_id(pnum):
            if pnum not in parent_cache:
                acc = get_by_number(pnum)
                parent_cache[pnum] = acc.id if acc else None
            return parent_cache[pnum]

        for ac in to_create:
            pid = _parent_id(ac['parent_number'])
            obj = Account(
                account_number=ac['account_number'],
                name=ac['name'],
                type=ac['type'],
                transaction_type=ac['transaction_type'],
                parent_id=pid,
                tracks_weight=ac['tracks_weight'],
            )
            db.session.add(obj)
            db.session.flush()
            created[ac['account_number']] = obj

        # المرحلة 2: ربط memo_account_id
        for ac in to_create:
            if not ac['memo_number']:
                continue
            obj  = created.get(ac['account_number'])
            memo = created.get(ac['memo_number']) or get_by_number(ac['memo_number'])
            if obj and memo:
                # الربط الثنائي عبر الخدمة المركزية فقط -- انظر account_pair_service.py
                link_accounts(obj, memo, created_by='create_missing_accounts')

        db.session.commit()

        print(f'\n✅  تم إنشاء {len(created)} حساب بنجاح.\n')
        print('  الخطوة التالية: شغّل opening_entry.py --apply لإنشاء القيد الافتتاحي.')


if __name__ == '__main__':
    main()
