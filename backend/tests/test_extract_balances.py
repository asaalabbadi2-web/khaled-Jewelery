"""
backend/tests/test_extract_balances.py
========================================
اختبارات أداة استخراج الأرصدة — تستخدم mock بدلاً من قاعدة بيانات حقيقية.
"""

from __future__ import annotations

import os
import sys
import types
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Mock psycopg2 قبل الاستيراد (لا نحتاج قاعدة بيانات فعلية في الاختبارات)
# ---------------------------------------------------------------------------

_psycopg2_mock = types.ModuleType("psycopg2")
_psycopg2_mock.extras = types.ModuleType("psycopg2.extras")
_psycopg2_mock.extras.RealDictCursor = object
_psycopg2_mock.OperationalError = Exception
_psycopg2_mock.connect = MagicMock()
sys.modules.setdefault("psycopg2", _psycopg2_mock)
sys.modules.setdefault("psycopg2.extras", _psycopg2_mock.extras)

# أضف المسار قبل الاستيراد
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "migration_v2"))
from extract_balances import (
    CustomerBalance,
    ExtractedSnapshot,
    InventoryBalance,
    OpeningEntry,
    OpeningEntryBuilder,
    SafeBoxBalance,
    SupplierBalance,
    V1PostgresReader,
    _mask_url,
    _to_dict,
    extract,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _snap(**kwargs) -> ExtractedSnapshot:
    defaults = dict(
        cutover_date="2026-04-02",
        extracted_at="2026-04-02T10:00:00",
        db_url_masked="postgresql://user:***@host/db",
    )
    defaults.update(kwargs)
    return ExtractedSnapshot(**defaults)


def _zero_weights():
    return dict(net_weight_18k=Decimal("0"), net_weight_21k=Decimal("0"),
                net_weight_22k=Decimal("0"), net_weight_24k=Decimal("0"))


# ---------------------------------------------------------------------------
# _mask_url
# ---------------------------------------------------------------------------

class TestMaskUrl:
    def test_masks_password(self):
        url = "postgresql://user:secret@myhost:5432/db"
        assert "secret" not in _mask_url(url)
        assert "***" in _mask_url(url)
        assert "myhost" in _mask_url(url)
        assert "5432" in _mask_url(url)

    def test_no_password_unchanged(self):
        url = "postgresql://myhost/db"
        assert _mask_url(url) == url

    def test_bad_url_returned_as_is(self):
        assert _mask_url("not-a-url") == "not-a-url"


# ---------------------------------------------------------------------------
# _to_dict
# ---------------------------------------------------------------------------

class TestToDict:
    def test_decimal_becomes_string(self):
        d = _to_dict(Decimal("123.456"))
        assert d == "123.456"
        assert isinstance(d, str)

    def test_list_of_decimals(self):
        result = _to_dict([Decimal("1"), Decimal("2")])
        assert result == ["1", "2"]

    def test_dataclass_serialized(self):
        inv = InventoryBalance(
            account_id=1, account_number="71310",
            name="مخزون", karat=21, net_weight=Decimal("10.5"),
        )
        d = _to_dict(inv)
        assert d["net_weight"] == "10.5"
        assert d["karat"] == 21

    def test_plain_values_pass_through(self):
        assert _to_dict(42) == 42
        assert _to_dict("hello") == "hello"
        assert _to_dict(None) is None


# ---------------------------------------------------------------------------
# OpeningEntryBuilder — Cash Only
# ---------------------------------------------------------------------------

class TestOpeningEntryBuilderCash:
    """سيناريو بسيط: خزينة نقدية + مورد."""

    def _make_snapshot(self):
        snap = _snap()
        snap.safe_boxes = [
            SafeBoxBalance(
                safe_box_id=1, name="صندوق النقدية", safe_type="cash",
                account_id=10, account_number="1110",
                cash_balance=Decimal("50000"),
                weight_18k=Decimal("0"), weight_21k=Decimal("0"),
                weight_22k=Decimal("0"), weight_24k=Decimal("0"),
            )
        ]
        snap.suppliers = [
            SupplierBalance(
                supplier_id=1, name="مورد A",
                financial_account_id=20, financial_account_number="2210",
                net_payable_sar=Decimal("30000"),
                weight_account_id=None, weight_account_number=None,
                **_zero_weights(),
            )
        ]
        return snap

    def test_builds_without_error(self):
        snap = self._make_snapshot()
        entry = OpeningEntryBuilder().build(snap)
        assert isinstance(entry, OpeningEntry)

    def test_cash_balanced(self):
        snap = self._make_snapshot()
        entry = OpeningEntryBuilder().build(snap)
        assert entry.is_cash_balanced, (
            f"مدين={entry.total_cash_debit} دائن={entry.total_cash_credit}"
        )

    def test_cash_safe_is_debit(self):
        snap = self._make_snapshot()
        entry = OpeningEntryBuilder().build(snap)
        safe_line = next(l for l in entry.lines if l.account_number == "1110")
        assert safe_line.side == "debit"
        assert safe_line.amount_sar == Decimal("50000")

    def test_supplier_is_credit(self):
        snap = self._make_snapshot()
        entry = OpeningEntryBuilder().build(snap)
        sup_line = next(l for l in entry.lines if l.account_number == "2210")
        assert sup_line.side == "credit"
        assert sup_line.amount_sar == Decimal("30000")

    def test_equity_balances_the_gap(self):
        """الفارق 20000 يذهب لحساب التسوية."""
        snap = self._make_snapshot()
        entry = OpeningEntryBuilder().build(snap)
        eq_line = next(l for l in entry.lines if l.account_number == "3100")
        assert eq_line.side == "credit"
        assert eq_line.amount_sar == Decimal("20000")

    def test_all_lines_have_account_number(self):
        snap = self._make_snapshot()
        entry = OpeningEntryBuilder().build(snap)
        for line in entry.lines:
            assert line.account_number, f"سطر بدون رقم حساب: {line}"


# ---------------------------------------------------------------------------
# OpeningEntryBuilder — Weight Accounts
# ---------------------------------------------------------------------------

class TestOpeningEntryBuilderWeight:
    """سيناريو: مخزون وزني + مورد بذمة وزنية."""

    def _make_snapshot(self):
        snap = _snap()
        snap.inventory = [
            InventoryBalance(
                account_id=100, account_number="71310",
                name="مخزون ذهب 21", karat=21, net_weight=Decimal("50.0"),
            )
        ]
        snap.suppliers = [
            SupplierBalance(
                supplier_id=2, name="مورد B",
                financial_account_id=None, financial_account_number=None,
                net_payable_sar=Decimal("0"),
                weight_account_id=200, weight_account_number="72200001",
                net_weight_18k=Decimal("0"),
                net_weight_21k=Decimal("50.0"),
                net_weight_22k=Decimal("0"),
                net_weight_24k=Decimal("0"),
            )
        ]
        return snap

    def test_weight_balanced(self):
        snap = self._make_snapshot()
        entry = OpeningEntryBuilder().build(snap)
        assert entry.is_weight_balanced, (
            f"مدين وزني 21={entry.total_weight_debit_21k} "
            f"دائن وزني 21={entry.total_weight_credit_21k}"
        )

    def test_inventory_is_debit(self):
        snap = self._make_snapshot()
        entry = OpeningEntryBuilder().build(snap)
        inv_line = next(l for l in entry.lines if l.account_number == "71310")
        assert inv_line.side == "debit"
        assert inv_line.weight_21k == Decimal("50.0")
        assert inv_line.is_weight_account is True

    def test_supplier_weight_is_credit(self):
        snap = self._make_snapshot()
        entry = OpeningEntryBuilder().build(snap)
        sup_line = next(l for l in entry.lines if l.account_number == "72200001")
        assert sup_line.side == "credit"
        assert sup_line.weight_21k == Decimal("50.0")

    def test_weight_lines_have_no_cash(self):
        snap = self._make_snapshot()
        entry = OpeningEntryBuilder().build(snap)
        for line in entry.lines:
            if line.is_weight_account:
                assert line.amount_sar == Decimal("0"), \
                    f"حساب وزني يحمل قيمة نقدية: {line}"


# ---------------------------------------------------------------------------
# OpeningEntryBuilder — Full Mixed Scenario
# ---------------------------------------------------------------------------

class TestOpeningEntryBuilderFull:
    """سيناريو كامل: خزائن + عملاء + موردون + مخزون وزني."""

    def _make_snapshot(self):
        snap = _snap()
        snap.safe_boxes = [
            SafeBoxBalance(
                safe_box_id=1, name="صندوق", safe_type="cash",
                account_id=10, account_number="1110",
                cash_balance=Decimal("44752.71"),
                weight_18k=Decimal("0"), weight_21k=Decimal("0"),
                weight_22k=Decimal("0"), weight_24k=Decimal("0"),
            ),
            SafeBoxBalance(
                safe_box_id=2, name="بنك الرياض", safe_type="bank",
                account_id=11, account_number="1120",
                cash_balance=Decimal("-10000"),
                weight_18k=Decimal("0"), weight_21k=Decimal("0"),
                weight_22k=Decimal("0"), weight_24k=Decimal("0"),
            ),
        ]
        snap.customers = [
            CustomerBalance(
                customer_id=1, name="عميل A",
                financial_account_id=30, financial_account_number="1210",
                net_receivable_sar=Decimal("5000"),
                weight_account_id=None, weight_account_number=None,
                **_zero_weights(),
            )
        ]
        snap.suppliers = [
            SupplierBalance(
                supplier_id=1, name="مورد A",
                financial_account_id=40, financial_account_number="2210",
                net_payable_sar=Decimal("14992.74"),
                weight_account_id=50, weight_account_number="72200001",
                net_weight_18k=Decimal("0"),
                net_weight_21k=Decimal("10.0"),
                net_weight_22k=Decimal("0"),
                net_weight_24k=Decimal("0"),
            )
        ]
        snap.inventory = [
            InventoryBalance(
                account_id=100, account_number="71310",
                name="مخزون 21", karat=21, net_weight=Decimal("10.0"),
            )
        ]
        return snap

    def test_cash_balanced(self):
        entry = OpeningEntryBuilder().build(self._make_snapshot())
        assert entry.is_cash_balanced

    def test_weight_balanced(self):
        entry = OpeningEntryBuilder().build(self._make_snapshot())
        assert entry.is_weight_balanced

    def test_correct_line_count(self):
        entry = OpeningEntryBuilder().build(self._make_snapshot())
        # صندوق + بنك (دائن لأنه سالب) + عميل + مورد مالي + مورد وزني + مخزون + تسوية
        assert len(entry.lines) >= 6

    def test_negative_cash_safe_is_credit(self):
        """بنك الرياض رصيده سالب = يجب أن يكون دائناً في قيد الافتتاح."""
        entry = OpeningEntryBuilder().build(self._make_snapshot())
        bank_line = next(l for l in entry.lines if l.account_number == "1120")
        assert bank_line.side == "credit"
        assert bank_line.amount_sar == Decimal("10000")

    def test_customer_receivable_is_debit(self):
        entry = OpeningEntryBuilder().build(self._make_snapshot())
        cust_line = next(l for l in entry.lines if l.account_number == "1210")
        assert cust_line.side == "debit"
        assert cust_line.party_type == "customer"

    def test_no_mixed_cash_weight_line(self):
        """لا يجب أن يحمل أي سطر نقداً ووزناً في نفس الوقت."""
        entry = OpeningEntryBuilder().build(self._make_snapshot())
        for line in entry.lines:
            has_cash   = line.amount_sar != Decimal("0")
            has_weight = any([
                line.weight_18k != Decimal("0"),
                line.weight_21k != Decimal("0"),
                line.weight_22k != Decimal("0"),
                line.weight_24k != Decimal("0"),
            ])
            assert not (has_cash and has_weight), \
                f"سطر يخلط نقد ووزن: {line}"


# ---------------------------------------------------------------------------
# V1PostgresReader._d
# ---------------------------------------------------------------------------

class TestDecimalConverter:
    def setup_method(self):
        # نصنع Reader بدون اتصال حقيقي
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = MagicMock()
        with patch("psycopg2.connect", return_value=mock_conn):
            self.reader = V1PostgresReader("postgresql://dummy/dummy")

    def test_none_returns_zero(self):
        assert self.reader._d(None) == Decimal("0")

    def test_string_decimal(self):
        assert self.reader._d("123.456") == Decimal("123.456")

    def test_float_rounded(self):
        result = self.reader._d(10.0005)
        assert result == Decimal("10.001")

    def test_integer(self):
        assert self.reader._d(500) == Decimal("500.000")

    def test_invalid_returns_zero(self):
        assert self.reader._d("not-a-number") == Decimal("0")


# ---------------------------------------------------------------------------
# Extract Integration (fully mocked)
# ---------------------------------------------------------------------------

class TestExtractMocked:
    """يختبر دالة extract() بـ mock كامل للـ DB."""

    def _make_mock_conn(self, suppliers=None, customers=None,
                        safe_boxes=None, cash_balances=None, weight_balances=None):
        """يبني mock يُرجع بيانات محددة."""
        mock_cur    = MagicMock()
        mock_conn   = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        s_rows = suppliers or []
        c_rows = customers or []
        sb_rows = safe_boxes or []
        inv_rows = []

        call_count = [0]
        cash_bals   = cash_balances  or {}    # account_id -> (debit, credit)
        weight_bals = weight_balances or {}   # account_id -> (w18, w21, w22, w24)

        def _execute(sql, params=()):
            # نتعرف على نوع الاستعلام من المحتوى
            sql_lower = sql.lower().strip()
            if "from supplier" in sql_lower:
                mock_cur.fetchall.return_value = s_rows
            elif "from customer" in sql_lower:
                mock_cur.fetchall.return_value = c_rows
            elif "from safe_box" in sql_lower:
                mock_cur.fetchall.return_value = sb_rows
            elif "account_number like '7130%'" in sql_lower:
                mock_cur.fetchall.return_value = inv_rows
            elif "sum(cash_debit)" in sql_lower and params:
                acc_id = params[0]
                d, c = cash_bals.get(acc_id, (0, 0))
                mock_cur.fetchone.return_value = {"d": d, "c": c}
            elif "sum(debit_18k)" in sql_lower and params:
                acc_id = params[0]
                w = weight_bals.get(acc_id, (0, 0, 0, 0))
                mock_cur.fetchone.return_value = {
                    "w18": w[0], "w21": w[1], "w22": w[2], "w24": w[3]
                }

        mock_cur.execute.side_effect = _execute
        return mock_conn

    def test_empty_db_produces_balanced_entry(self):
        mock_conn = self._make_mock_conn()
        with patch("psycopg2.connect", return_value=mock_conn):
            snapshot, entry = extract("postgresql://dummy/db", "2026-04-02")
        assert entry.is_cash_balanced
        assert entry.is_weight_balanced
        assert len(snapshot.suppliers) == 0

    def test_snapshot_fields_populated(self):
        sb_row = {
            "id": 1, "name": "صندوق", "safe_type": "cash",
            "account_id": 10, "account_number": "1110",
        }
        mock_conn = self._make_mock_conn(
            safe_boxes=[sb_row],
            cash_balances={10: (50000, 0)},
        )
        with patch("psycopg2.connect", return_value=mock_conn):
            snapshot, entry = extract("postgresql://user:pass@host/db", "2026-04-02")
        assert "pass" not in snapshot.db_url_masked
        assert "***"  in snapshot.db_url_masked
