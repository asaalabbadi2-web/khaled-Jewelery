#!/usr/bin/env python3
"""
أداة تشخيص ربح الجرام — تُظهر تفاصيل كل فاتورة بيع لتحديد سبب انخفاض متوسط سعر البيع/جرام.

Usage (inside docker):
    docker exec -it yasargold-backend python3 devtools/diagnose_gram_profit.py

Or locally:
    cd backend && python3 devtools/diagnose_gram_profit.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from models import db, Invoice, InvoiceItem, Item, InvoiceKaratLine, Settings
from sqlalchemy import func
from sqlalchemy.orm import joinedload
from datetime import datetime, timedelta
from config import MAIN_KARAT


def get_main_karat():
    settings = Settings.query.first()
    return settings.main_karat if settings else MAIN_KARAT

def run():
    with app.app_context():
        main_karat = get_main_karat()
        print(f"═══ تشخيص ربح الجرام ═══")
        print(f"العيار الرئيسي: {main_karat}")
        print()

        # This year
        now = datetime.now()
        start_dt = datetime(now.year, 1, 1)
        end_dt = now + timedelta(days=1)

        sell_invoices = (
            Invoice.query
            .filter(Invoice.invoice_type.in_(['بيع', 'sell']))
            .filter(Invoice.date >= start_dt, Invoice.date < end_dt)
            .filter(func.coalesce(Invoice.is_posted, False) == True)
            .options(
                joinedload(Invoice.karat_lines),
                joinedload(Invoice.items).joinedload(InvoiceItem.item),
            )
            .order_by(Invoice.date.asc())
            .all()
        )

        print(f"فواتير البيع المرحّلة ({start_dt.date()} → {now.date()}): {len(sell_invoices)}")
        print()

        # ── Per-invoice breakdown ──
        rows = []
        for inv in sell_invoices:
            cash = float(inv.total or 0)
            raw_w = float(inv.total_weight or 0)

            # Compute main-karat weight
            mk_weight = 0.0
            source = 'fallback'

            kl = inv.karat_lines or []
            if kl:
                source = 'karat_lines'
                for line in kl:
                    w = float(getattr(line, 'weight_grams', 0) or 0)
                    k = float(getattr(line, 'karat', main_karat) or main_karat)
                    if w > 0:
                        mk_weight += w * k / main_karat

            if mk_weight <= 0:
                inv_items = inv.items or []
                if inv_items:
                    source = 'items'
                    for ii in inv_items:
                        qty = float(ii.quantity or 1)
                        w = float(getattr(ii, 'weight', 0) or 0)
                        k = float(getattr(ii, 'karat', 0) or 0)
                        if w > 0 and k > 0:
                            mk_weight += (w * k / main_karat) * qty
                        else:
                            item_obj = ii.item
                            if item_obj:
                                mk_weight += float(item_obj.weight_in_main_karat() or 0) * qty

            if mk_weight <= 0:
                source = 'fallback'
                mk_weight = raw_w

            avg = cash / mk_weight if mk_weight > 0 else 0
            gold_sub = float(inv.gold_subtotal or 0)
            wage_sub = float(inv.wage_subtotal or 0)
            rows.append({
                'id': inv.id,
                'date': str(inv.date)[:10] if inv.date else '?',
                'cash': cash,
                'gold_sub': gold_sub,
                'wage_sub': wage_sub,
                'raw_w': raw_w,
                'mk_w': mk_weight,
                'avg': avg,
                'source': source,
                'n_kl': len(kl),
                'n_items': len(inv.items or []),
            })

        # ── Summary stats ──
        total_cash = sum(r['cash'] for r in rows)
        total_gold_sub = sum(r['gold_sub'] for r in rows)
        total_wage_sub = sum(r['wage_sub'] for r in rows)
        total_mk_w = sum(r['mk_w'] for r in rows)
        total_raw_w = sum(r['raw_w'] for r in rows)
        overall_avg = total_cash / total_mk_w if total_mk_w > 0 else 0

        print(f"إجمالي المبيعات النقدية (total): {total_cash:,.2f} ر.س")
        print(f"إجمالي قيمة الذهب (gold_subtotal): {total_gold_sub:,.2f} ر.س")
        print(f"إجمالي الأجور (wage_subtotal): {total_wage_sub:,.2f} ر.س")
        print(f"إجمالي الوزن الخام (total_weight): {total_raw_w:,.3f} جم")
        print(f"إجمالي الوزن المعادل ({main_karat}): {total_mk_w:,.3f} جم")
        print(f"متوسط سعر البيع/جم (total/weight_mk): {overall_avg:,.2f} ر.س")
        print(f"متوسط سعر البيع/جم (total/weight_raw): {total_cash / total_raw_w if total_raw_w > 0 else 0:,.2f} ر.س")
        if total_gold_sub > 0:
            print(f"متوسط سعر الذهب/جم (gold_sub/weight_mk): {total_gold_sub / total_mk_w if total_mk_w > 0 else 0:,.2f} ر.س")
        print()

        # ── Monthly breakdown ──
        from collections import defaultdict
        by_month = defaultdict(lambda: {'count': 0, 'cash': 0, 'weight': 0})
        for r in rows:
            m = r['date'][:7]  # YYYY-MM
            by_month[m]['count'] += 1
            by_month[m]['cash'] += r['cash']
            by_month[m]['weight'] += r['mk_w']

        print("── تفصيل شهري ──")
        for m in sorted(by_month.keys()):
            d = by_month[m]
            avg_m = d['cash'] / d['weight'] if d['weight'] > 0 else 0
            print(f"  {m}: {d['count']:4d} فاتورة | {d['cash']:>12,.2f} ر.س | {d['weight']:>10,.3f} جم | avg={avg_m:,.2f}/جم")
        print()

        # ── Source distribution ──
        by_source = {}
        for r in rows:
            s = r['source']
            if s not in by_source:
                by_source[s] = {'count': 0, 'cash': 0, 'weight': 0}
            by_source[s]['count'] += 1
            by_source[s]['cash'] += r['cash']
            by_source[s]['weight'] += r['mk_w']

        print("── توزيع مصدر الوزن ──")
        for s, d in by_source.items():
            avg_s = d['cash'] / d['weight'] if d['weight'] > 0 else 0
            print(f"  {s:15s}: {d['count']:4d} فاتورة | {d['cash']:>12,.2f} ر.س | {d['weight']:>10,.3f} جم | avg={avg_s:,.2f}/جم")
        print()

        # ── Outliers: invoices with very low avg_sell ──
        print("── أقل 20 فاتورة بيع (سعر/جم) ──")
        sorted_rows = sorted(rows, key=lambda r: r['avg'])
        for r in sorted_rows[:20]:
            flag = " ⚠️" if r['avg'] < 300 else ""
            print(f"  #{r['id']:5d} | {r['date']} | total={r['cash']:>10,.2f} gold_sub={r['gold_sub']:>10,.2f} wage={r['wage_sub']:>8,.2f} | raw={r['raw_w']:>8,.3f}جم | mk({main_karat})={r['mk_w']:>8,.3f}جم | avg={r['avg']:>8,.2f}/جم | {r['source']}({r['n_kl']}kl,{r['n_items']}it){flag}")
        print()

        # ── Outliers: very high weight invoices ──
        print("── أكبر 10 فواتير بيع (وزن) ──")
        sorted_w = sorted(rows, key=lambda r: -r['mk_w'])
        for r in sorted_w[:10]:
            print(f"  #{r['id']:5d} | {r['date']} | total={r['cash']:>10,.2f} | mk({main_karat})={r['mk_w']:>8,.3f}جم | avg={r['avg']:>8,.2f}/جم | {r['source']}")
        print()

        # ── Karat lines breakdown: check if weight_grams is raw or converted ──
        print("── عينة من karat_lines (أول 10 فواتير بيع ذات karat != 21) ──")
        count = 0
        for inv in sell_invoices:
            for kl in (inv.karat_lines or []):
                if kl.karat and abs(kl.karat - main_karat) > 0.1:
                    ratio = float(inv.total_weight or 0) / float(kl.weight_grams) if kl.weight_grams else 0
                    print(f"  Invoice #{inv.id} | karat={kl.karat} | weight_grams={kl.weight_grams} | inv.total_weight={inv.total_weight} | ratio={ratio:.3f}")
                    count += 1
                    if count >= 10:
                        break
            if count >= 10:
                break

        if count == 0:
            print("  (لا توجد كرات لاينز بعيار مختلف عن الرئيسي)")
        print()

        # ── Check for sell invoices with zero weight or zero total ──
        zero_weight = [r for r in rows if r['mk_w'] <= 0.001]
        zero_cash = [r for r in rows if r['cash'] <= 0.01]
        print(f"فواتير بدون وزن: {len(zero_weight)}")
        print(f"فواتير بدون مبلغ: {len(zero_cash)}")
        for r in zero_weight[:5]:
            print(f"  ⚠️ #{r['id']} cash={r['cash']} raw_w={r['raw_w']} source={r['source']}")
        for r in zero_cash[:5]:
            print(f"  ⚠️ #{r['id']} cash={r['cash']} mk_w={r['mk_w']} source={r['source']}")


if __name__ == '__main__':
    run()
