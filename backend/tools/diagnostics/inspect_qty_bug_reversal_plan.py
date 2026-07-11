"""
inspect_qty_bug_reversal_plan.py
===================================
لكل فاتورة "بيع"/new من الفواتير المتأثرة بمشكلة تضخيم الوزن على حساب 760،
يبحث في *كل* أسطر القيد (لا فقط حساب 760) عن أي سطر وزن (debit/credit_Xk > 0)
لنفس العيار الذي تأثر فيه حساب 760، ويحسب:

  factor_k = excess_k(760) / |je_cur_760_k|

ثم لكل سطر وزن آخر بنفس العيار k في نفس القيد، يحسب:
  reversal_amount = |line_value_k| * factor_k

ويُجمّع reversal_amount حسب (account_id, karat) عبر كل الفواتير المتأثرة،
ليعطينا صورة كاملة عن: أي الحسابات ستحتاج قيد عكسي، وبأي مقدار إجمالي،
قبل بناء سكربت التطبيق.

يتحقق أيضاً أن نسبة (line_value_k / je_cur_760_k) ثابتة لكل أسطر القيد لنفس
العيار (أي factor واحد لكل (invoice, karat))، ويطبع أي حالة شاذة.

قراءة فقط.

تشغيل:
    docker exec yasargold-backend python backend/inspect_qty_bug_reversal_plan.py --account-id 760
"""

import os
import sys
import argparse
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db, JournalEntry, JournalEntryLine, Invoice, InvoiceItem, Account
from routes import convert_to_main_karat


KARATS = (18, 21, 22, 24)
EPS = 1e-6


def run(account_id: int):
    with app.app_context():
        # All JE lines on account 760, grouped by invoice
        lines_760 = (
            JournalEntryLine.query
            .join(JournalEntry)
            .filter(
                JournalEntryLine.account_id == account_id,
                JournalEntry.is_deleted == False,
                JournalEntryLine.is_deleted == False,
                JournalEntry.is_posted == True,
                JournalEntry.reference_type == 'invoice',
            )
            .all()
        )

        je_by_inv = defaultdict(list)
        for line in lines_760:
            entry = line.journal_entry
            inv_id = getattr(entry, 'reference_id', None)
            je_by_inv[inv_id].append((line, entry.id))

        reversal_by_account_karat = defaultdict(float)  # (account_id, karat) -> sum
        affected_count = 0
        anomalies = []

        for inv_id, line_je_pairs in je_by_inv.items():
            inv = Invoice.query.get(inv_id) if inv_id else None
            if not inv:
                continue
            if getattr(inv, 'invoice_type', None) != 'بيع' or (getattr(inv, 'gold_type', None) or 'new') != 'new':
                continue

            je_ids = set(je_id for _, je_id in line_je_pairs)

            # je_cur_760_k: net (debit-credit) on account 760 for this invoice, per karat
            je_cur_760 = {k: 0.0 for k in KARATS}
            for l, _ in line_je_pairs:
                for k in KARATS:
                    je_cur_760[k] += (getattr(l, f'debit_{k}k') or 0) - (getattr(l, f'credit_{k}k') or 0)

            # correct_k from items
            items = InvoiceItem.query.filter_by(invoice_id=inv_id).all()
            correct = {k: 0.0 for k in KARATS}
            for it in items:
                k = int(round(float(it.karat or 0)))
                w = float(it.weight or 0)
                if k not in KARATS or w <= 0:
                    continue
                correct[k] += w

            je_main = sum(convert_to_main_karat(je_cur_760[k], k) for k in KARATS)
            correct_main = sum(convert_to_main_karat(correct[k], k) for k in KARATS)
            if abs(abs(je_main) - correct_main) < 0.01:
                continue  # not affected

            affected_count += 1

            factor = {}
            for k in KARATS:
                if abs(je_cur_760[k]) > EPS:
                    excess_k = abs(je_cur_760[k]) - correct[k]
                    factor[k] = excess_k / abs(je_cur_760[k])
                else:
                    factor[k] = 0.0

            # Now scan ALL lines of these JE(s) for any weight line in affected karats
            all_lines = (
                JournalEntryLine.query
                .filter(
                    JournalEntryLine.journal_entry_id.in_(je_ids),
                    JournalEntryLine.is_deleted == False,
                )
                .all()
            )

            # group by (account_id, karat) -> net value, to check uniform ratio
            net_by_acc_karat = defaultdict(float)
            for l in all_lines:
                for k in KARATS:
                    if factor.get(k, 0.0) <= EPS:
                        continue
                    v = (getattr(l, f'debit_{k}k') or 0) - (getattr(l, f'credit_{k}k') or 0)
                    if abs(v) > EPS:
                        net_by_acc_karat[(l.account_id, k)] += v

            for (acc_id, k), net_v in net_by_acc_karat.items():
                reversal_amount = abs(net_v) * factor[k]
                reversal_by_account_karat[(acc_id, k)] += reversal_amount

                # sanity: ratio check vs account 760's own ratio
                ratio = abs(net_v) / abs(je_cur_760[k]) if abs(je_cur_760[k]) > EPS else None
                if ratio is not None and acc_id != account_id and abs(ratio - 1.0) > 0.02:
                    anomalies.append((inv.invoice_number, acc_id, k, net_v, je_cur_760[k], ratio))

        print(f"عدد الفواتير المتأثرة: {affected_count}\n")
        print("إجمالي 'مبلغ العكس' المطلوب لكل (حساب، عيار):")
        for (acc_id, k), total in sorted(reversal_by_account_karat.items()):
            acc = Account.query.get(acc_id)
            print(f"  account=[{acc_id}] {acc.account_number if acc else '?'} "
                  f"{acc.name if acc else '?'}  karat={k}: {total:,.3f}")

        if anomalies:
            print(f"\nحالات شاذة (نسبة != 1.0 مقارنة بحساب {account_id}): {len(anomalies)}")
            for a in anomalies[:20]:
                print(f"   invoice={a[0]} account={a[1]} karat={a[2]} "
                      f"line_net={a[3]:.3f} acc760_net={a[4]:.3f} ratio={a[5]:.3f}")
        else:
            print("\nلا توجد حالات شاذة - كل الأسطر بنفس النسبة لحساب 760 في كل فاتورة.")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--account-id', type=int, required=True)
    args = parser.parse_args()
    run(account_id=args.account_id)
