"""
migration_v2/extract_balances.py
==================================
أداة استخراج الأرصدة من النظام القديم (v1 — PostgreSQL على Docker)
وتوليد قيد افتتاح جاهز للنظام الجديد (v2).

الاستخدام:
    python extract_balances.py \\
        --db-url "postgresql://user:pass@host:5432/yasargold" \\
        [--cutover-date 2026-04-02] \\
        [--output opening_entry.json]

أو عبر متغير البيئة:
    V1_DB_URL="postgresql://..." python extract_balances.py

الأداة تقرأ فقط (read-only transaction) ولا تعدّل قاعدة البيانات الأصلية.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print("psycopg2 غير مثبت. قم بتثبيته:")
    print("  pip install psycopg2-binary")
    sys.exit(1)


# ─────────────────────────────────────────────
# Data Structures
# ─────────────────────────────────────────────

@dataclass
class SupplierBalance:
    supplier_id: int
    name: str
    financial_account_id: Optional[int]
    financial_account_number: Optional[str]
    net_payable_sar: Decimal          # موجب = نحن مدينون له
    weight_account_id: Optional[int]
    weight_account_number: Optional[str]
    net_weight_18k: Decimal
    net_weight_21k: Decimal
    net_weight_22k: Decimal
    net_weight_24k: Decimal


@dataclass
class CustomerBalance:
    customer_id: int
    name: str
    financial_account_id: Optional[int]
    financial_account_number: Optional[str]
    net_receivable_sar: Decimal       # موجب = مدين لنا
    weight_account_id: Optional[int]
    weight_account_number: Optional[str]
    net_weight_18k: Decimal
    net_weight_21k: Decimal
    net_weight_22k: Decimal
    net_weight_24k: Decimal


@dataclass
class SafeBoxBalance:
    safe_box_id: int
    name: str
    safe_type: str
    account_id: int
    account_number: str
    cash_balance: Decimal
    weight_18k: Decimal
    weight_21k: Decimal
    weight_22k: Decimal
    weight_24k: Decimal


@dataclass
class InventoryBalance:
    account_id: int
    account_number: str
    name: str
    karat: int
    net_weight: Decimal


@dataclass
class ExtractedSnapshot:
    cutover_date: str
    extracted_at: str
    db_url_masked: str

    suppliers: List[SupplierBalance] = field(default_factory=list)
    customers: List[CustomerBalance] = field(default_factory=list)
    safe_boxes: List[SafeBoxBalance] = field(default_factory=list)
    inventory: List[InventoryBalance] = field(default_factory=list)

    # أرصدة إجمالية للتدقيق
    total_cash_assets: Decimal = Decimal("0")       # مجموع أصول نقدية
    total_receivables: Decimal = Decimal("0")       # ذمم عملاء
    total_payables: Decimal = Decimal("0")          # ذمم موردين
    total_inventory_21k: Decimal = Decimal("0")    # إجمالي مخزون عيار 21
    total_inventory_18k: Decimal = Decimal("0")
    total_inventory_22k: Decimal = Decimal("0")
    total_inventory_24k: Decimal = Decimal("0")


@dataclass
class OpeningEntryLine:
    """سطر في قيد الافتتاح."""
    account_id: Optional[int]
    account_number: str
    account_name: str
    is_weight_account: bool
    side: str                         # debit / credit
    amount_sar: Decimal               # للحسابات المالية
    weight_18k: Decimal               # للحسابات الوزنية
    weight_21k: Decimal
    weight_22k: Decimal
    weight_24k: Decimal
    description: str
    party_type: Optional[str] = None  # supplier / customer / None
    party_id: Optional[int] = None
    party_name: Optional[str] = None


@dataclass
class OpeningEntry:
    """قيد الافتتاح الكامل."""
    date: str
    description: str
    lines: List[OpeningEntryLine] = field(default_factory=list)

    # إحصائيات للتحقق
    total_cash_debit: Decimal = Decimal("0")
    total_cash_credit: Decimal = Decimal("0")
    total_weight_debit_21k: Decimal = Decimal("0")
    total_weight_credit_21k: Decimal = Decimal("0")
    is_cash_balanced: bool = False
    is_weight_balanced: bool = False


# ---------------------------------------------------------------------------
# Database Reader (PostgreSQL)
# ---------------------------------------------------------------------------

class V1PostgresReader:
    """يقرأ قاعدة بيانات v1 PostgreSQL بصلاحيات قراءة فقط."""

    def __init__(self, db_url: str):
        self.conn = psycopg2.connect(db_url)
        self.conn.set_session(readonly=True, autocommit=False)
        self.cur = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    def close(self):
        self.cur.close()
        self.conn.close()

    def _q(self, sql: str, params=()) -> List[dict]:
        self.cur.execute(sql, params)
        return self.cur.fetchall()

    @staticmethod
    def _d(v) -> Decimal:
        if v is None:
            return Decimal("0")
        try:
            return Decimal(str(v)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
        except Exception:
            return Decimal("0")

    def _cash_balance(self, account_id: int) -> Decimal:
        self.cur.execute("""
            SELECT
                COALESCE(SUM(cash_debit), 0)  AS d,
                COALESCE(SUM(cash_credit), 0) AS c
            FROM journal_entry_line
            WHERE account_id = %s
              AND (is_deleted IS NULL OR is_deleted = FALSE)
        """, (account_id,))
        row = self.cur.fetchone()
        return self._d(row["d"]) - self._d(row["c"]) if row else Decimal("0")

    def _weight_balance(self, account_id: int) -> Dict[int, Decimal]:
        self.cur.execute("""
            SELECT
                COALESCE(SUM(debit_18k),0) - COALESCE(SUM(credit_18k),0) AS w18,
                COALESCE(SUM(debit_21k),0) - COALESCE(SUM(credit_21k),0) AS w21,
                COALESCE(SUM(debit_22k),0) - COALESCE(SUM(credit_22k),0) AS w22,
                COALESCE(SUM(debit_24k),0) - COALESCE(SUM(credit_24k),0) AS w24
            FROM journal_entry_line
            WHERE account_id = %s
              AND (is_deleted IS NULL OR is_deleted = FALSE)
        """, (account_id,))
        row = self.cur.fetchone()
        if not row:
            return {18: Decimal("0"), 21: Decimal("0"), 22: Decimal("0"), 24: Decimal("0")}
        return {
            18: self._d(row["w18"]), 21: self._d(row["w21"]),
            22: self._d(row["w22"]), 24: self._d(row["w24"]),
        }

    def read_suppliers(self) -> List[SupplierBalance]:
        rows = self._q("""
            SELECT s.id, s.name, s.account_id,
                   a.account_number, a.memo_account_id,
                   am.account_number AS memo_number
            FROM supplier s
            LEFT JOIN account a  ON a.id  = s.account_id
            LEFT JOIN account am ON am.id = a.memo_account_id
            ORDER BY s.id
        """)
        result = []
        for r in rows:
            fin_id  = r["account_id"]
            memo_id = r["memo_account_id"]
            fin_bal = self._cash_balance(fin_id) if fin_id else Decimal("0")
            w_bal   = self._weight_balance(memo_id) if memo_id else {k: Decimal("0") for k in [18,21,22,24]}
            if (abs(fin_bal) < Decimal("0.01") and
                    all(abs(v) < Decimal("0.001") for v in w_bal.values())):
                continue
            result.append(SupplierBalance(
                supplier_id=r["id"], name=r["name"],
                financial_account_id=fin_id,
                financial_account_number=r["account_number"],
                net_payable_sar=fin_bal,
                weight_account_id=memo_id,
                weight_account_number=r["memo_number"],
                net_weight_18k=w_bal[18], net_weight_21k=w_bal[21],
                net_weight_22k=w_bal[22], net_weight_24k=w_bal[24],
            ))
        return result

    def read_customers(self) -> List[CustomerBalance]:
        rows = self._q("""
            SELECT c.id, c.name, c.account_id,
                   a.account_number, a.memo_account_id,
                   am.account_number AS memo_number
            FROM customer c
            LEFT JOIN account a  ON a.id  = c.account_id
            LEFT JOIN account am ON am.id = a.memo_account_id
            ORDER BY c.id
        """)
        result = []
        for r in rows:
            fin_id  = r["account_id"]
            memo_id = r["memo_account_id"]
            fin_bal = self._cash_balance(fin_id) if fin_id else Decimal("0")
            w_bal   = self._weight_balance(memo_id) if memo_id else {k: Decimal("0") for k in [18,21,22,24]}
            if (abs(fin_bal) < Decimal("0.01") and
                    all(abs(v) < Decimal("0.001") for v in w_bal.values())):
                continue
            result.append(CustomerBalance(
                customer_id=r["id"], name=r["name"],
                financial_account_id=fin_id,
                financial_account_number=r["account_number"],
                net_receivable_sar=fin_bal,
                weight_account_id=memo_id,
                weight_account_number=r["memo_number"],
                net_weight_18k=w_bal[18], net_weight_21k=w_bal[21],
                net_weight_22k=w_bal[22], net_weight_24k=w_bal[24],
            ))
        return result

    def read_safe_boxes(self) -> List[SafeBoxBalance]:
        rows = self._q("""
            SELECT sb.id, sb.name, sb.safe_type, sb.account_id,
                   a.account_number
            FROM safe_box sb
            JOIN account a ON a.id = sb.account_id
            WHERE sb.is_active = TRUE
            ORDER BY sb.safe_type, sb.name
        """)
        result = []
        for r in rows:
            acc_id   = r["account_id"]
            cash_bal = self._cash_balance(acc_id)
            w_bal    = self._weight_balance(acc_id)
            if (abs(cash_bal) < Decimal("0.01") and
                    all(abs(v) < Decimal("0.001") for v in w_bal.values())):
                continue
            result.append(SafeBoxBalance(
                safe_box_id=r["id"], name=r["name"],
                safe_type=r["safe_type"],
                account_id=acc_id,
                account_number=r["account_number"],
                cash_balance=cash_bal,
                weight_18k=w_bal[18], weight_21k=w_bal[21],
                weight_22k=w_bal[22], weight_24k=w_bal[24],
            ))
        return result

    def read_inventory(self) -> List[InventoryBalance]:
        rows = self._q("""
            SELECT a.id, a.account_number, a.name
            FROM account a
            WHERE a.account_number LIKE '7130%%'
            ORDER BY a.account_number
        """)
        karat_map = {
            "71300": 18, "7130000": 18,
            "71310": 21, "7130001": 21, "7130100": 21,
            "71320": 22, "7130200": 22,
            "71330": 24, "7130300": 24,
        }
        result = []
        for r in rows:
            acc_id  = r["id"]
            acc_num = r["account_number"]
            w_bal   = self._weight_balance(acc_id)
            if all(abs(v) < Decimal("0.001") for v in w_bal.values()):
                continue
            karat = karat_map.get(acc_num)
            if karat is None:
                karat = max(
                    [(18, abs(w_bal[18])), (21, abs(w_bal[21])),
                     (22, abs(w_bal[22])), (24, abs(w_bal[24]))],
                    key=lambda x: x[1]
                )[0]
            net = w_bal[karat]
            if abs(net) < Decimal("0.001"):
                for k, w in w_bal.items():
                    if abs(w) >= Decimal("0.001"):
                        result.append(InventoryBalance(
                            account_id=acc_id, account_number=acc_num,
                            name=r["name"], karat=k, net_weight=w,
                        ))
                continue
            result.append(InventoryBalance(
                account_id=acc_id, account_number=acc_num,
                name=r["name"], karat=karat, net_weight=net,
            ))
        return result


# ─────────────────────────────────────────────
# Opening Entry Builder
# ─────────────────────────────────────────────

class OpeningEntryBuilder:
    """يبني قيد الافتتاح من اللقطة المستخرجة."""

    # حسابات النظام الجديد (v2) — قابلة للتعديل
    V2_ACCOUNTS = {
        "equity_opening":    {"number": "3100", "name": "حساب تسوية الافتتاح"},
        "inventory_18k":     {"number": "71300", "name": "مخزون ذهب عيار 18 (وزني)"},
        "inventory_21k":     {"number": "71310", "name": "مخزون ذهب عيار 21 (وزني)"},
        "inventory_22k":     {"number": "71320", "name": "مخزون ذهب عيار 22 (وزني)"},
        "inventory_24k":     {"number": "71330", "name": "مخزون ذهب عيار 24 (وزني)"},
    }

    def build(self, snapshot: ExtractedSnapshot) -> OpeningEntry:
        entry = OpeningEntry(
            date=snapshot.cutover_date,
            description=f"قيد الافتتاح - تاريخ التحول للنظام الجديد {snapshot.cutover_date}",
        )

        total_cash_debit = Decimal("0")
        total_cash_credit = Decimal("0")
        balancing_amount = Decimal("0")   # لحساب التسوية في النهاية

        # ───────────────────────────────────
        # 1. الخزائن النقدية — أصول
        # ───────────────────────────────────
        for sb in snapshot.safe_boxes:
            if sb.safe_type in ("cash", "bank", "clearing") and abs(sb.cash_balance) >= Decimal("0.01"):
                side = "debit" if sb.cash_balance > 0 else "credit"
                amt = abs(sb.cash_balance)
                entry.lines.append(OpeningEntryLine(
                    account_id=sb.account_id,
                    account_number=sb.account_number,
                    account_name=sb.name,
                    is_weight_account=False,
                    side=side,
                    amount_sar=amt,
                    weight_18k=Decimal("0"), weight_21k=Decimal("0"),
                    weight_22k=Decimal("0"), weight_24k=Decimal("0"),
                    description=f"افتتاح خزينة [{sb.name}]",
                ))
                if side == "debit":
                    total_cash_debit += amt
                    balancing_amount += amt
                else:
                    total_cash_credit += amt
                    balancing_amount -= amt

        # ───────────────────────────────────
        # 2. ذمم العملاء — أصول
        # ───────────────────────────────────
        for c in snapshot.customers:
            if abs(c.net_receivable_sar) >= Decimal("0.01") and c.financial_account_id:
                side = "debit" if c.net_receivable_sar > 0 else "credit"
                amt = abs(c.net_receivable_sar)
                entry.lines.append(OpeningEntryLine(
                    account_id=c.financial_account_id,
                    account_number=c.financial_account_number or "",
                    account_name=c.name,
                    is_weight_account=False,
                    side=side,
                    amount_sar=amt,
                    weight_18k=Decimal("0"), weight_21k=Decimal("0"),
                    weight_22k=Decimal("0"), weight_24k=Decimal("0"),
                    description=f"افتتاح ذمة عميل [{c.name}]",
                    party_type="customer",
                    party_id=c.customer_id,
                    party_name=c.name,
                ))
                if side == "debit":
                    total_cash_debit += amt
                    balancing_amount += amt
                else:
                    total_cash_credit += amt
                    balancing_amount -= amt

            # الذمة الوزنية للعميل
            for karat, weight in [(18, c.net_weight_18k), (21, c.net_weight_21k),
                                   (22, c.net_weight_22k), (24, c.net_weight_24k)]:
                if abs(weight) >= Decimal("0.001") and c.weight_account_id:
                    side = "debit" if weight > 0 else "credit"
                    w_kwargs = self._weight_kwargs(karat, abs(weight))
                    entry.lines.append(OpeningEntryLine(
                        account_id=c.weight_account_id,
                        account_number=c.weight_account_number or "",
                        account_name=f"{c.name} (وزني)",
                        is_weight_account=True,
                        side=side,
                        amount_sar=Decimal("0"),
                        **w_kwargs,
                        description=f"افتتاح ذهب عميل [{c.name}] عيار {karat}",
                        party_type="customer",
                        party_id=c.customer_id,
                        party_name=c.name,
                    ))

        # ───────────────────────────────────
        # 3. ذمم الموردين — التزامات
        # ───────────────────────────────────
        for s in snapshot.suppliers:
            if abs(s.net_payable_sar) >= Decimal("0.01") and s.financial_account_id:
                # net_payable_sar موجب = نحن مدينون للمورد (دائن في قيد الافتتاح)
                side = "credit" if s.net_payable_sar > 0 else "debit"
                amt = abs(s.net_payable_sar)
                entry.lines.append(OpeningEntryLine(
                    account_id=s.financial_account_id,
                    account_number=s.financial_account_number or "",
                    account_name=s.name,
                    is_weight_account=False,
                    side=side,
                    amount_sar=amt,
                    weight_18k=Decimal("0"), weight_21k=Decimal("0"),
                    weight_22k=Decimal("0"), weight_24k=Decimal("0"),
                    description=f"افتتاح ذمة مورد [{s.name}]",
                    party_type="supplier",
                    party_id=s.supplier_id,
                    party_name=s.name,
                ))
                if side == "credit":
                    total_cash_credit += amt
                    balancing_amount -= amt
                else:
                    total_cash_debit += amt
                    balancing_amount += amt

            # الذمة الوزنية للمورد
            for karat, weight in [(18, s.net_weight_18k), (21, s.net_weight_21k),
                                   (22, s.net_weight_22k), (24, s.net_weight_24k)]:
                if abs(weight) >= Decimal("0.001") and s.weight_account_id:
                    # net_weight موجب = التزام وزني على المورد (دائن)
                    side = "credit" if weight > 0 else "debit"
                    w_kwargs = self._weight_kwargs(karat, abs(weight))
                    entry.lines.append(OpeningEntryLine(
                        account_id=s.weight_account_id,
                        account_number=s.weight_account_number or "",
                        account_name=f"{s.name} (وزني)",
                        is_weight_account=True,
                        side=side,
                        amount_sar=Decimal("0"),
                        **w_kwargs,
                        description=f"افتتاح ذهب مورد [{s.name}] عيار {karat}",
                        party_type="supplier",
                        party_id=s.supplier_id,
                        party_name=s.name,
                    ))

        # ───────────────────────────────────
        # 4. المخزون الوزني — لا قيمة مالية
        # ───────────────────────────────────
        inv_acc_map = {
            18: self.V2_ACCOUNTS["inventory_18k"],
            21: self.V2_ACCOUNTS["inventory_21k"],
            22: self.V2_ACCOUNTS["inventory_22k"],
            24: self.V2_ACCOUNTS["inventory_24k"],
        }
        for inv in snapshot.inventory:
            if abs(inv.net_weight) < Decimal("0.001"):
                continue
            acc_info = inv_acc_map.get(inv.karat)
            if not acc_info:
                continue
            side = "debit" if inv.net_weight > 0 else "credit"
            w_kwargs = self._weight_kwargs(inv.karat, abs(inv.net_weight))
            entry.lines.append(OpeningEntryLine(
                account_id=None,           # يُحدَّد عند الاستيراد حسب رقم الحساب
                account_number=acc_info["number"],
                account_name=acc_info["name"],
                is_weight_account=True,
                side=side,
                amount_sar=Decimal("0"),
                **w_kwargs,
                description=f"افتتاح مخزون عيار {inv.karat} (من {inv.account_number})",
            ))

        # ───────────────────────────────────
        # 5. الخزائن الذهبية (وزني فقط)
        # ───────────────────────────────────
        for sb in snapshot.safe_boxes:
            if sb.safe_type == "gold":
                for karat, weight in [(18, sb.weight_18k), (21, sb.weight_21k),
                                       (22, sb.weight_22k), (24, sb.weight_24k)]:
                    if abs(weight) >= Decimal("0.001"):
                        side = "debit" if weight > 0 else "credit"
                        w_kwargs = self._weight_kwargs(karat, abs(weight))
                        entry.lines.append(OpeningEntryLine(
                            account_id=sb.account_id,
                            account_number=sb.account_number,
                            account_name=f"{sb.name} (وزني)",
                            is_weight_account=True,
                            side=side,
                            amount_sar=Decimal("0"),
                            **w_kwargs,
                            description=f"افتتاح خزينة ذهبية [{sb.name}] عيار {karat}",
                        ))

        # ───────────────────────────────────
        # 6. حساب التسوية (يوازن الفارق النقدي)
        # ───────────────────────────────────
        if abs(balancing_amount) >= Decimal("0.01"):
            eq_acc = self.V2_ACCOUNTS["equity_opening"]
            # إذا المدين > الدائن: حساب التسوية دائن
            side = "credit" if balancing_amount > 0 else "debit"
            entry.lines.append(OpeningEntryLine(
                account_id=None,
                account_number=eq_acc["number"],
                account_name=eq_acc["name"],
                is_weight_account=False,
                side=side,
                amount_sar=abs(balancing_amount),
                weight_18k=Decimal("0"), weight_21k=Decimal("0"),
                weight_22k=Decimal("0"), weight_24k=Decimal("0"),
                description="حساب تسوية افتتاح — الفارق بين الأصول والالتزامات",
            ))
            if side == "credit":
                total_cash_credit += abs(balancing_amount)
            else:
                total_cash_debit += abs(balancing_amount)

        # ───────────────────────────────────
        # 7. تسوية الفوارق الوزنية لكل عيار
        # (النظام القديم لم يكن يوازن الوزن بدقة لكل عيار على حدة)
        # ───────────────────────────────────
        eq_acc = self.V2_ACCOUNTS["equity_opening"]
        for karat in (18, 21, 22, 24):
            fd = f"weight_{karat}k"
            wd = sum(getattr(l, fd) for l in entry.lines if l.is_weight_account and l.side == "debit")
            wc = sum(getattr(l, fd) for l in entry.lines if l.is_weight_account and l.side == "credit")
            diff = wd - wc
            if abs(diff) >= Decimal("0.001"):
                side = "credit" if diff > 0 else "debit"
                w_kwargs = self._weight_kwargs(karat, abs(diff))
                entry.lines.append(OpeningEntryLine(
                    account_id=None,
                    account_number=eq_acc["number"],
                    account_name=eq_acc["name"],
                    is_weight_account=True,
                    side=side,
                    amount_sar=Decimal("0"),
                    **w_kwargs,
                    description=f"تسوية وزنية افتتاح عيار {karat} — فارق النظام القديم",
                ))

        # ───────────────────────────────────
        # إحصائيات التوازن
        # ───────────────────────────────────
        entry.total_cash_debit = total_cash_debit
        entry.total_cash_credit = total_cash_credit
        entry.is_cash_balanced = abs(total_cash_debit - total_cash_credit) < Decimal("0.01")

        for karat in (18, 21, 22, 24):
            fd = f"weight_{karat}k"
            wd = sum(getattr(l, fd) for l in entry.lines if l.is_weight_account and l.side == "debit")
            wc = sum(getattr(l, fd) for l in entry.lines if l.is_weight_account and l.side == "credit")
            if karat == 21:
                entry.total_weight_debit_21k = wd
                entry.total_weight_credit_21k = wc

        all_weight_balanced = True
        for karat in (18, 21, 22, 24):
            fd = f"weight_{karat}k"
            wd = sum(getattr(l, fd) for l in entry.lines if l.is_weight_account and l.side == "debit")
            wc = sum(getattr(l, fd) for l in entry.lines if l.is_weight_account and l.side == "credit")
            if abs(wd - wc) > Decimal("0.001"):
                all_weight_balanced = False
                break
        entry.is_weight_balanced = all_weight_balanced

        return entry

    @staticmethod
    def _weight_kwargs(karat: int, weight: Decimal) -> dict:
        return {
            "weight_18k": weight if karat == 18 else Decimal("0"),
            "weight_21k": weight if karat == 21 else Decimal("0"),
            "weight_22k": weight if karat == 22 else Decimal("0"),
            "weight_24k": weight if karat == 24 else Decimal("0"),
        }


# ---------------------------------------------------------------------------
# JSON Serialization
# ---------------------------------------------------------------------------

def _to_dict(obj):
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, list):
        return [_to_dict(i) for i in obj]
    if hasattr(obj, "__dataclass_fields__"):
        return {k: _to_dict(getattr(obj, k)) for k in obj.__dataclass_fields__}
    return obj


def _mask_url(url: str) -> str:
    try:
        from urllib.parse import urlparse, urlunparse
        p = urlparse(url)
        if p.password:
            netloc = f"{p.username}:***@{p.hostname}"
            if p.port:
                netloc += f":{p.port}"
            return urlunparse(p._replace(netloc=netloc))
    except Exception:
        pass
    return url


# ─────────────────────────────────────────────
# Report Printer
# ─────────────────────────────────────────────

def print_report(snapshot: ExtractedSnapshot, entry: OpeningEntry):
    SEP = "─" * 65

    print(f"\n{'═'*65}")
    print(f"  \u062aقرير استخراج الأرصدة — النظام القديم v1 (PostgreSQL)")
    print(f"  تاريخ الاستخراج: {snapshot.extracted_at}")
    print(f"  تاريخ القطع:     {snapshot.cutover_date}")
    print(f"  قاعدة البيانات:  {snapshot.db_url_masked}")
    print(f"{'═'*65}\n")

    # موردون
    print(f"{'الموردون':}")
    print(SEP)
    suppliers_with_balance = snapshot.suppliers
    if suppliers_with_balance:
        print(f"  {'الاسم':<30} {'ذمة (ريال)':>12} {'وزن 21 (جرام)':>14}")
        print(f"  {'-'*30} {'-'*12} {'-'*14}")
        for s in suppliers_with_balance:
            print(f"  {s.name:<30} {s.net_payable_sar:>12.2f} {s.net_weight_21k:>14.3f}")
    else:
        print("  لا يوجد موردون برصيد")

    # عملاء
    print(f"\n{'العملاء':}")
    print(SEP)
    if snapshot.customers:
        print(f"  {'الاسم':<30} {'ذمة (ريال)':>12} {'وزن 21 (جرام)':>14}")
        print(f"  {'-'*30} {'-'*12} {'-'*14}")
        for c in snapshot.customers:
            print(f"  {c.name:<30} {c.net_receivable_sar:>12.2f} {c.net_weight_21k:>14.3f}")
    else:
        print("  لا يوجد عملاء برصيد")

    # خزائن
    print(f"\n{'الخزائن':}")
    print(SEP)
    if snapshot.safe_boxes:
        print(f"  {'الاسم':<35} {'النوع':<8} {'الرصيد':>12}")
        print(f"  {'-'*35} {'-'*8} {'-'*12}")
        for sb in snapshot.safe_boxes:
            if sb.safe_type in ("cash", "bank", "clearing"):
                print(f"  {sb.name:<35} {sb.safe_type:<8} {sb.cash_balance:>12.2f}")
            else:
                w21 = sb.weight_21k
                if abs(w21) >= Decimal("0.001"):
                    print(f"  {sb.name:<35} {'gold':<8} {w21:>11.3f}g")
    else:
        print("  لا يوجد خزائن برصيد")

    # مخزون
    print(f"\n{'المخزون الوزني':}")
    print(SEP)
    if snapshot.inventory:
        print(f"  {'الحساب':<12} {'الاسم':<35} {'عيار':>5} {'وزن (جرام)':>12}")
        print(f"  {'-'*12} {'-'*35} {'-'*5} {'-'*12}")
        for inv in snapshot.inventory:
            print(f"  {inv.account_number:<12} {inv.name:<35} {inv.karat:>5} {inv.net_weight:>12.3f}")
    else:
        print("  لا يوجد مخزون وزني")

    # قيد الافتتاح
    print(f"\n{'قيد الافتتاح المُولَّد':}")
    print(SEP)
    print(f"  إجمالي مدين نقدي: {entry.total_cash_debit:>12.2f} ريال")
    print(f"  إجمالي دائن نقدي: {entry.total_cash_credit:>12.2f} ريال")
    print(f"  توازن نقدي:       {'✓ متوازن' if entry.is_cash_balanced else '✗ غير متوازن — يحتاج مراجعة'}")
    print(f"  توازن وزني:       {'✓ متوازن' if entry.is_weight_balanced else '✗ غير متوازن — يحتاج مراجعة'}")
    print(f"  عدد السطور:       {len(entry.lines)}")

    if not entry.is_cash_balanced or not entry.is_weight_balanced:
        print(f"\n  ⚠️  تحذير: قيد الافتتاح يحتاج مراجعة يدوية قبل الاستيراد!")


# ---------------------------------------------------------------------------
# Core Extract Function
# ---------------------------------------------------------------------------

def extract(db_url: str, cutover_date: str) -> Tuple[ExtractedSnapshot, OpeningEntry]:
    reader = V1PostgresReader(db_url)
    try:
        snapshot = ExtractedSnapshot(
            cutover_date=cutover_date,
            extracted_at=datetime.now().isoformat(timespec="seconds"),
            db_url_masked=_mask_url(db_url),
        )
        snapshot.suppliers  = reader.read_suppliers()
        snapshot.customers  = reader.read_customers()
        snapshot.safe_boxes = reader.read_safe_boxes()
        snapshot.inventory  = reader.read_inventory()

        snapshot.total_payables = sum(
            s.net_payable_sar for s in snapshot.suppliers if s.net_payable_sar > 0
        )
        snapshot.total_receivables = sum(
            c.net_receivable_sar for c in snapshot.customers if c.net_receivable_sar > 0
        )
        snapshot.total_cash_assets = sum(
            sb.cash_balance for sb in snapshot.safe_boxes
            if sb.safe_type in ("cash", "bank") and sb.cash_balance > 0
        )
        snapshot.total_inventory_21k = sum(
            inv.net_weight for inv in snapshot.inventory if inv.karat == 21
        )
        snapshot.total_inventory_18k = sum(
            inv.net_weight for inv in snapshot.inventory if inv.karat == 18
        )

        entry = OpeningEntryBuilder().build(snapshot)
        return snapshot, entry
    finally:
        reader.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="استخراج الأرصدة من v1 PostgreSQL وتوليد قيد افتتاح v2"
    )
    parser.add_argument(
        "--db-url",
        default=os.environ.get("V1_DB_URL", ""),
        help="مثال: postgresql://user:pass@host:5432/yasargold (أو V1_DB_URL env)",
    )
    parser.add_argument(
        "--cutover-date",
        default=date.today().isoformat(),
        help="تاريخ القطع YYYY-MM-DD (افتراضي: اليوم)",
    )
    parser.add_argument("--output",          default="opening_entry.json")
    parser.add_argument("--snapshot-output", default="balance_snapshot.json")
    args = parser.parse_args()

    if not args.db_url:
        parser.error(
            "يجب تحديد --db-url أو تعيين V1_DB_URL\n"
            "  مثال: postgresql://yasargold:password@192.168.1.10:5432/yasargold"
        )

    print(f"Connecting to: {_mask_url(args.db_url)}")
    try:
        snapshot, entry = extract(args.db_url, args.cutover_date)
    except psycopg2.OperationalError as e:
        print(f"Connection failed:\n  {e}")
        return 1

    print_report(snapshot, entry)

    Path(args.snapshot_output).write_text(
        json.dumps(_to_dict(snapshot), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nSnapshot saved:       {args.snapshot_output}")

    Path(args.output).write_text(
        json.dumps(_to_dict(entry), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Opening entry saved:  {args.output}")

    return 0 if entry.is_cash_balanced else 1


if __name__ == "__main__":
    raise SystemExit(main())
