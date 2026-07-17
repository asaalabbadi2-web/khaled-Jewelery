# Core Extraction Matrix — routes/__init__.py → Packages

**Generated from:** `grep "from routes import" backend/routes/*.py`
**Last updated:** 2026-07-12
**Status legend:** ⏳ Pending · 🔄 In Progress · ✅ Done

---

## Criticality Definition

| Risk | Criteria |
|------|----------|
| 🔴 High | تؤثر مباشرة على القيود المالية، الأرصدة، أو تُستخدم في 5+ domains |
| 🟡 Medium | منطق أعمال واضح، 3–4 domains، لا تكتب إلى DB مباشرة |
| 🟢 Low | تحويل، تنسيق، قراءة فقط — قابلة للاستبدال بأمان |

---

## Family 1 — Karat Engine
> ليست Helpers. هذه Domain Service خاصة بمنطق العيارات.
> **الوجهة:** `pricing/karat_service.py`

| Helper | # Consumers | Risk | Consumers | Status |
|--------|-------------|------|-----------|--------|
| `convert_to_main_karat` | 10 | 🔴 High | Acc, Cat, Clr, Cus, Inv, Jnl, OffRes, Rep, SBx, Sup | ✅ |
| `get_main_karat` | 6 | 🔴 High | Clr, Jnl, OffRes, SBx, Sys, Vch | ✅ |

**Dependency budget:** استخراج هذا الـ Family وحده يُقلل اعتماديات 10 domains على routes/__init__.py.

---

## Family 2 — Voucher Engine
> ليست Helpers. هذه Voucher Engine — قد تتحول لاحقًا إلى Service مستقل.
> **الوجهة:** `accounting/voucher_engine.py`

| Helper | # Consumers | Risk | Consumers | Status |
|--------|-------------|------|-----------|--------|
| `generate_voucher_number` | 5 | 🔴 High | Clr, OffRes, SBx, Sys, Vch | ✅ |
| `create_journal_entry_from_voucher` | 5 | 🔴 High | Clr, OffRes, SBx, Sys, Vch | ✅ |
| `_append_safe_transactions_for_voucher` | 4 | 🔴 High | Clr, OffRes, SBx, Vch | ✅ |
| `_generate_journal_entry_number` | 4 | 🟡 Medium | Clr, Inv, OffRes, Vch | ✅ |
| `_update_account_balances_from_journal_lines` | 1 | 🔴 High | Jnl | ✅ |

---

## Family 3 — Statement Verification
> ليست QR عامة. هذه Capability: التحقق من صحة كشوف الحسابات.
> **الوجهة:** `accounting/statement_verification.py`

| Helper | # Consumers | Risk | Consumers | Status |
|--------|-------------|------|-----------|--------|
| `_sign_qr_payload` | 4 | 🟡 Medium | Acc, Cus, Sup, Sys | ✅ |
| `_build_statement_qr_signed_payload` | 3 | 🟡 Medium | Acc, Cus, Sup | ✅ |
| `_build_qr_verify_token` | 3 | 🟡 Medium | Acc, Cus, Sup | ✅ |
| `_build_statement_verify_url` | 3 | 🟡 Medium | Acc, Cus, Sup | ✅ |

---

## Core Infrastructure
> أدوات عامة بلا منطق أعمال — تنتمي إلى `core/`

| Helper | # Consumers | Risk | Target | Consumers | Status |
|--------|-------------|------|--------|-----------|--------|
| `_db_has_column` | 6 | 🟡 Medium | `core/database.py` | Acc, Cus, Inv, Jnl, Sup, Sys | ✅ |
| `_coerce_float` | 5 | 🟢 Low | `core/number_helpers.py` | Clr, Jnl, OffRes, Sys, Vch | ✅ |
| `_wrap_api_exceptions` | 4 | 🟢 Low | `core/responses.py` | Acc, Inv, Sup, Sys | ✅ |
| `_parse_iso_date` | 4 | 🟢 Low | `core/dates.py` | Cat, Emp, Rep, Sup | ✅ |
| `_parse_iso_time` | 1 | 🟢 Low | `core/dates.py` | Emp | ✅ |

---

## Accounting Helpers
> منطق أعمال محاسبي مشترك — تنتمي إلى `accounting/`

| Helper | # Consumers | Risk | Target | Consumers | Status |
|--------|-------------|------|--------|-----------|--------|
| `get_account_id_for_mapping` | 4 | 🟡 Medium | `accounting/mappings.py` | Clr, Inv, OffRes, Rep | ⏳ |
| `get_account_id_by_number` | 3 | 🟡 Medium | `accounting/mappings.py` | Inv, Rep, Sup | ⏳ |
| `DEFAULT_MAPPING_OPERATION_TYPE` | 1 | 🟡 Medium | `accounting/mappings.py` | Inv | ⏳ |
| `_get_settings_singleton` | 3 | 🟡 Medium | `core/settings.py` | Emp, Rep, Sys | ⏳ |
| `get_current_gold_price` | 3 | 🔴 High | `pricing/gold_price_service.py` (already exists) | Clr, Inv, Jnl | ⏳ |
| `_load_weight_closing_settings` | 4 | 🔴 High | `accounting/weight_closing.py` | Clr, Inv, OffRes, Sys | ⏳ |
| `_auto_consume_weight_closing` | 2 | 🔴 High | `accounting/weight_closing.py` | Clr, OffRes | ⏳ |
| `_recalculate_account_balances_for_accounts` | 2 | 🔴 High | `accounting/balances.py` | OffRes, Sys | ⏳ |
| `_rebuild_safe_box_transactions_for_journal_entry` | 2 | 🔴 High | `accounting/safe_boxes.py` | Jnl, OffRes | ⏳ |
| `_ensure_safe_box_transactions_for_invoice_je` | 1 | 🔴 High | `accounting/safe_boxes.py` | SBx | ⏳ |
| `_ensure_manufacturing_wage_expense_account` | 2 | 🟡 Medium | `accounting/wages.py` | Inv, Rep | ⏳ |
| `_ensure_gold24k_commission_revenue_account` | 1 | 🟡 Medium | `accounting/wages.py` | Inv | ⏳ |
| `get_inventory_average_cost` | 1 | 🔴 High | `accounting/inventory.py` | Inv | ⏳ |

---

## Invoice Domain — Single Consumer (Low Priority)
> تُستخدم فقط في invoices.py — تبقى في routes حتى يُستخرج domain الفواتير بالكامل.

| Helper | Risk | Target (مستقبلي) |
|--------|------|-----------------|
| `create_item_from_invoice_payload` | 🔴 High | `invoices/item_creation.py` |
| `InlineItemCreationError` | 🔴 High | `invoices/item_creation.py` |
| `validate_bridge_account_balance` | 🔴 High | `accounting/bridge.py` |
| `_next_invoice_type_id` | 🟡 Medium | `accounting/sequences.py` |
| `_resolve_inventory_account_id_for_invoice` | 🟡 Medium | `accounting/inventory.py` |
| `_get_inventory_account_by_karat` | 🟡 Medium | `accounting/inventory.py` |
| `_get_manufacturing_wage_mode` | 🟡 Medium | `accounting/wages.py` |
| `_get_manufacturing_wage_inventory_account_id` | 🟡 Medium | `accounting/wages.py` |
| `_try_process_due_auto_clearing_settlements` | 🔴 High | `settlements/auto_clearing.py` |
| `DEFAULT_MAPPING_OPERATION_TYPE` | 🟡 Medium | `accounting/mappings.py` |

---

## Dependency Budget per Domain
> عدد الـ helpers التي يحتاج Domain استخراجها قبل أن يصبح مستقلاً عن routes/__init__.py

| Domain | Helpers المطلوبة | Families المطلوبة | جهة الاستخراج |
|--------|-----------------|-------------------|---------------|
| **Catalog** | 2 | Karat Engine + core/dates | ✅ أسهل بداية لـ Commerce API |
| **Suppliers** | 5 | Karat + QR/Statements + dates + db | 🟡 متوسط |
| **Customers** | 4 | Karat + QR/Statements + db | 🟡 متوسط |
| **Accounts** | 4 | Karat + QR/Statements + db + responses | 🟡 متوسط |
| **Journals** | 5 | Karat + Voucher Engine + db + coerce | 🔴 عالي |
| **Vouchers** | 5 | Voucher Engine + karat + coerce | 🔴 عالي |
| **Clearing** | 9 | Voucher Engine + karat + weight_closing + gold_price | 🔴 عالي |
| **Invoices** | 17 | الكل | 🔴 أعقد domain |

---

## Target Package Structure

```
backend/
├── pricing/
│     karat_service.py          ← Family 1: convert_to_main_karat, get_main_karat
│     gold_price_service.py     ← already exists ✅
│
├── accounting/
│     voucher_engine.py         ← Family 2: generate_voucher_number, create_journal_entry_from_voucher, ...
│     statement_verification.py ← Family 3: _sign_qr_payload, _build_statement_*, _verify_statement_token
│     mappings.py               ← get_account_id_for_mapping, get_account_id_by_number
│     weight_closing.py         ← _load_weight_closing_settings, _auto_consume_weight_closing
│     balances.py               ← _recalculate_account_balances_for_accounts
│     safe_boxes.py             ← _append_safe_transactions_for_voucher, _rebuild_safe_box_transactions
│     wages.py                  ← manufacturing wage helpers
│     inventory.py              ← _get_inventory_account_by_karat, get_inventory_average_cost
│     sequences.py              ← _next_invoice_type_id, _generate_journal_entry_number
│
├── core/
│     database.py               ← _db_has_column
│     responses.py              ← _wrap_api_exceptions
│     dates.py                  ← _parse_iso_date, _parse_iso_time
│     number_helpers.py         ← _coerce_float
│     settings.py               ← _get_settings_singleton
│
└── routes/
      __init__.py               ← يختفي تدريجياً مع كل استخراج
      *.py                      ← domains يستوردون من pricing/ + accounting/ + core/
```

---

## Migration Order (Recommended)

1. `pricing/karat_service.py` — يُحرر 10 domains دفعة واحدة
2. `core/` (dates, coerce, db, responses) — قاعدة لكل Domain
3. `accounting/voucher_engine.py` — يُحرر Clearing + OffRes + SBx + Vch + Sys
4. `accounting/statement_verification.py` — يُحرر Acc + Cus + Sup + Sys
5. `accounting/mappings.py` + `weight_closing.py`
6. ما تبقى بحسب Priority Commerce API
