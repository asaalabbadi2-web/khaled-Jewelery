# Opening Entries Fixes - Summary

## Problems Fixed

### 1. ✅ Entries didn't affect safebox balances

**Problem:** Journal entries were not updating the stored account balances in the database.

**Solution:**
- Added `_update_account_balances_from_journal_lines()` function in `backend/routes.py`
- Hooked into `add_journal_entry()` and `update_journal_entry()`
- Created `backend/recalculate_balances.py` script to sync existing data

**Modified Files:**
- `backend/routes.py`: Automatic balance updates
- `backend/recalculate_balances.py`: Script to recalculate all balances

**Usage:**
```bash
cd backend
./venv/bin/python recalculate_balances.py
```

---

### 2. ✅ Opening balance not shown separately in statements

**Problem:** Opening entries appeared as regular movements without a separate opening balance section.

**Solution:**
- Modified `get_account_statement()` in `backend/routes.py`
- Calculate opening balance from entries with type `افتتاحي`
- Exclude opening entries from movement list
- Added detailed gold opening balance fields

**Modified Files:**
- `backend/routes.py`: Filter opening entries and calculate opening balance
- `frontend/lib/models/account_statement_model.dart`: Added `openingBalanceGoldDetails`

**API Response Added:**
```json
{
  "opening_balance_cash": 10000.0,
  "opening_balance_gold_normalized": 50.0,
  "opening_balance_gold_details": {
    "18k": 0.0,
    "21k": 50.0,
    "22k": 0.0,
    "24k": 0.0
  }
}
```

---

### 3. ✅ Financial and memo accounts not merged in statements

**Problem:** When recording cash in financial account and weight in memo account, they appeared as separate movements.

**Solution:**
- Created new endpoint `/api/accounts/<id>/statement_merged`
- Merged journal lines from financial account and linked memo account
- Grouped lines by `journal_entry_id` to display single movement

**Modified Files:**
- `backend/routes.py`: Added `get_account_statement_merged()`
- `frontend/lib/api_service.dart`: Added `getAccountStatementMerged()`
- `frontend/lib/screens/account_statement_screen.dart`: Added "Merge Accounts" button

**Features:**
- Automatic detection of linked account (financial → memo or memo → financial)
- Smart grouping of movements from same entry
- Information about merged accounts in response

**Usage:**
1. Open account statement for any account
2. Enable "Merge Accounts" option from toolbar
3. Movements from financial and memo accounts will be merged

---

## Technical Implementation

### Automatic Balance Update System

When adding or updating a journal entry:
1. Identifies all affected accounts (old and new)
2. For each account, recalculates balance from:
   - All journal entry lines (`JournalEntryLine`)
   - All voucher account lines (`VoucherAccountLine`)
3. Updates `balance_cash` and `balance_18k/21k/22k/24k` in `Account` table

### Opening Entries Exclusion

Entries with type `افتتاحي`:
- Counted in opening balance only
- Not shown in movements list
- Used as starting point for running balances

### Account Merging

Financial and linked memo accounts:
- `Account.memo_account_id` links financial account to memo account
- Financial account contains cash
- Memo account (`tracks_weight=True`) contains weights
- When merging, lines are grouped by `journal_entry_id`

---

## Testing

### 1. Test Balance Updates:
```bash
cd backend
./venv/bin/python recalculate_balances.py
```

**Expected Output:**
```
🔄 Recalculating balances for 48 accounts...
✅ 15 - Cash Box: 10000.00 → 0.00
✅ Successfully updated 1 account
```

### 2. Test Opening Balance:
1. Create opening entry (`entry_type='افتتاحي'`)
2. Open account statement
3. Verify opening balance appears separately

### 3. Test Merging:
1. Create entry with:
   - Line in financial account (cash)
   - Line in linked memo account (weight)
2. Open financial account statement
3. Enable "Merge Accounts"
4. Verify single line showing both cash and weight

---

## Affected Files

### Backend:
- `backend/routes.py`: Modified `get_account_statement()` and added new endpoints
- `backend/recalculate_balances.py`: New script for balance recalculation

### Frontend:
- `frontend/lib/models/account_statement_model.dart`: Added `openingBalanceGoldDetails`
- `frontend/lib/api_service.dart`: Added `getAccountStatementMerged()`
- `frontend/lib/screens/account_statement_screen.dart`: Added "Merge Accounts" toggle

---

## Date & Status
- **Date:** 2025-01-23
- **Developer:** GitHub Copilot (Claude Sonnet 4.5)
- **Status:** Completed ✅
