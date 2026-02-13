#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import math
import sys
import urllib.error
import urllib.request


def _get_json(url: str, timeout: float = 10.0):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _as_float(value) -> float:
    try:
        return float(value or 0.0)
    except Exception:
        return 0.0


def _approx(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol


def _balances_by_id(balances_payload: dict) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for k, v in (balances_payload or {}).items():
        try:
            key = int(k)
        except Exception:
            continue
        out[key] = v if isinstance(v, dict) else {}
    return out


def _pick_accounts(accounts: list[dict], *, non_zero: bool, limit: int | None) -> list[dict]:
    if not non_zero:
        picked = list(accounts)
    else:
        picked = []
        for a in accounts:
            b = a.get("balances") if isinstance(a, dict) else None
            b = b if isinstance(b, dict) else {}
            cash = _as_float(b.get("cash"))
            w = b.get("weight") if isinstance(b.get("weight"), dict) else {}
            w_total = _as_float(w.get("total"))
            if abs(cash) > 0.01 or abs(w_total) > 0.001:
                picked.append(a)

    if limit is not None:
        picked = picked[: max(0, int(limit))]

    return picked


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify the 'single source of truth' balance invariant across endpoints.\n"
            "Checks that balances derived from /api/accounts/balances reconcile with statement endpoints." 
        )
    )
    parser.add_argument("--base", default="http://127.0.0.1:8001", help="Backend base URL")
    parser.add_argument(
        "--account-number",
        action="append",
        dest="account_numbers",
        help="Account number to verify (repeatable). If omitted, uses --non-zero selection.",
    )
    parser.add_argument(
        "--non-zero",
        action="store_true",
        help="Verify only accounts with non-zero live balances (from /api/accounts).",
    )
    parser.add_argument("--limit", type=int, default=None, help="Limit number of accounts checked")
    parser.add_argument("--tol-cash", type=float, default=0.01, help="Cash tolerance")
    parser.add_argument("--tol-weight", type=float, default=0.001, help="Weight tolerance")
    args = parser.parse_args(argv)

    base_api = args.base.rstrip("/") + "/api"

    try:
        accounts = _get_json(base_api + "/accounts")
        balances_payload = _get_json(base_api + "/accounts/balances")
    except urllib.error.URLError as exc:
        print(f"ERROR: failed to fetch from {base_api}: {exc}")
        return 2

    accounts = accounts if isinstance(accounts, list) else []
    balances_by_id = _balances_by_id(balances_payload)

    # Index for memo linking.
    by_id: dict[int, dict] = {}
    by_number: dict[str, dict] = {}
    financial_by_memo_id: dict[int, dict] = {}
    for a in accounts:
        if not isinstance(a, dict):
            continue
        try:
            aid = int(a.get("id"))
        except Exception:
            continue
        by_id[aid] = a
        by_number[str(a.get("account_number"))] = a

    for a in accounts:
        if not isinstance(a, dict):
            continue
        memo_id = a.get("memo_account_id")
        try:
            memo_id_int = int(memo_id) if memo_id is not None else None
        except Exception:
            memo_id_int = None
        if memo_id_int is not None:
            financial_by_memo_id[memo_id_int] = a

    if args.account_numbers:
        picked = []
        for n in args.account_numbers:
            a = by_number.get(str(n))
            if a:
                picked.append(a)
            else:
                print(f"WARN: account_number not found: {n}")
    else:
        picked = _pick_accounts(accounts, non_zero=args.non_zero, limit=args.limit)

    if not picked:
        print("No accounts selected")
        return 0

    failures: list[str] = []

    for acc in picked:
        acc_id = int(acc["id"])
        acc_no = str(acc.get("account_number"))
        name = acc.get("name")

        b = balances_by_id.get(acc_id, {})
        b_cash = _as_float(b.get("cash"))
        b_18 = _as_float(b.get("gold_18k"))
        b_21 = _as_float(b.get("gold_21k"))
        b_22 = _as_float(b.get("gold_22k"))
        b_24 = _as_float(b.get("gold_24k"))

        st = _get_json(base_api + f"/accounts/{acc_id}/statement")
        st_cash = _as_float(st.get("closing_balance_cash"))
        st_details = st.get("closing_balance_gold_details") if isinstance(st.get("closing_balance_gold_details"), dict) else {}
        st_18 = _as_float(st_details.get("18k"))
        st_21 = _as_float(st_details.get("21k"))
        st_22 = _as_float(st_details.get("22k"))
        st_24 = _as_float(st_details.get("24k"))

        ok_statement = (
            _approx(b_cash, st_cash, args.tol_cash)
            and _approx(b_18, st_18, args.tol_weight)
            and _approx(b_21, st_21, args.tol_weight)
            and _approx(b_22, st_22, args.tol_weight)
            and _approx(b_24, st_24, args.tol_weight)
        )

        stm = _get_json(base_api + f"/accounts/{acc_id}/statement_merged")
        stm_is_merged = bool(stm.get("is_merged"))
        stm_cash = _as_float(stm.get("closing_balance_cash"))
        stm_details = stm.get("closing_balance_gold_details") if isinstance(stm.get("closing_balance_gold_details"), dict) else {}
        stm_18 = _as_float(stm_details.get("18k"))
        stm_21 = _as_float(stm_details.get("21k"))
        stm_22 = _as_float(stm_details.get("22k"))
        stm_24 = _as_float(stm_details.get("24k"))

        # Decide what to compare statement_merged against:
        # - if no memo linkage, it should match the single-account balance.
        # - if memo linkage exists, compare against the combined (financial + memo) balances.
        memo_id = acc.get("memo_account_id")
        memo_id_int = None
        try:
            memo_id_int = int(memo_id) if memo_id is not None else None
        except Exception:
            memo_id_int = None

        fin_for_this_memo = financial_by_memo_id.get(acc_id)

        merged_expected_cash = b_cash
        merged_expected_18 = b_18
        merged_expected_21 = b_21
        merged_expected_22 = b_22
        merged_expected_24 = b_24

        merged_scope = "single"

        # Case A: this account is financial (has memo_account_id)
        if memo_id_int is not None:
            merged_scope = "financial+memo"
            memo_bal = balances_by_id.get(memo_id_int, {})
            merged_expected_cash += _as_float(memo_bal.get("cash"))
            merged_expected_18 += _as_float(memo_bal.get("gold_18k"))
            merged_expected_21 += _as_float(memo_bal.get("gold_21k"))
            merged_expected_22 += _as_float(memo_bal.get("gold_22k"))
            merged_expected_24 += _as_float(memo_bal.get("gold_24k"))

        # Case B: this account is memo (find financial pointing to it)
        elif fin_for_this_memo is not None:
            merged_scope = "financial+memo"
            fin_id = int(fin_for_this_memo["id"])
            fin_bal = balances_by_id.get(fin_id, {})
            merged_expected_cash += _as_float(fin_bal.get("cash"))
            merged_expected_18 += _as_float(fin_bal.get("gold_18k"))
            merged_expected_21 += _as_float(fin_bal.get("gold_21k"))
            merged_expected_22 += _as_float(fin_bal.get("gold_22k"))
            merged_expected_24 += _as_float(fin_bal.get("gold_24k"))

        ok_merged = (
            _approx(merged_expected_cash, stm_cash, args.tol_cash)
            and _approx(merged_expected_18, stm_18, args.tol_weight)
            and _approx(merged_expected_21, stm_21, args.tol_weight)
            and _approx(merged_expected_22, stm_22, args.tol_weight)
            and _approx(merged_expected_24, stm_24, args.tol_weight)
        )

        status = "OK" if (ok_statement and ok_merged) else "FAIL"
        print(f"{status} account_number={acc_no} id={acc_id} name={name} merged_scope={merged_scope} merged={stm_is_merged}")

        if not ok_statement:
            failures.append(
                f"statement mismatch for {acc_no} (id={acc_id}): balances cash={b_cash} gold21={b_21} vs statement cash={st_cash} gold21={st_21}"
            )
        if not ok_merged:
            failures.append(
                f"merged mismatch for {acc_no} (id={acc_id}, scope={merged_scope}): expected gold21={merged_expected_21} got {stm_21}"
            )

    if failures:
        print("\nFAILURES")
        for f in failures:
            print("-", f)
        return 1

    print("\nAll selected accounts reconcile.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
