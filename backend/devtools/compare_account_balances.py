#!/usr/bin/env python3

import argparse
import json
import sys
import urllib.error
import urllib.request


def _get_json(url: str, timeout: float = 8.0):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compare the same account's balances across key API endpoints: "
            "/api/accounts/balances, /api/accounts/<id>/statement, /api/accounts/<id>/statement_merged"
        )
    )
    parser.add_argument("--base", default="http://127.0.0.1:8001", help="Backend base URL")
    parser.add_argument("--account-number", required=True, help="Account number to lookup")
    parser.add_argument("--json", action="store_true", help="Emit a single JSON object")
    args = parser.parse_args(argv)

    base_api = args.base.rstrip("/") + "/api"
    account_no = str(args.account_number)

    try:
        accounts = _get_json(base_api + "/accounts")
    except urllib.error.URLError as exc:
        print(f"ERROR: failed to GET {base_api}/accounts: {exc}")
        return 2

    matched = [a for a in accounts if str(a.get("account_number")) == account_no]
    print("account_matches", len(matched))
    if not matched:
        # Provide a small hint for debugging.
        by_name = [a for a in accounts if account_no in str(a.get("account_number", ""))]
        if by_name:
            print("partial_matches")
            for a in by_name[:10]:
                print(" ", a.get("account_number"), a.get("id"), a.get("name"))
        return 0

    acc = matched[0]
    acc_id = acc.get("id")
    if not args.json:
        print("account_id", acc_id)
        print("account_number", acc.get("account_number"))
        print("account_name", acc.get("name"))

    balances = _get_json(base_api + "/accounts/balances")
    b = balances.get(str(acc_id)) or balances.get(acc_id)
    b = b if isinstance(b, dict) else {}

    st = _get_json(base_api + f"/accounts/{acc_id}/statement")
    stm = _get_json(base_api + f"/accounts/{acc_id}/statement_merged")

    merged_note = None
    try:
        if bool(stm.get('is_merged')):
            returned_acc_id = stm.get('account_id')
            returned_acc_no = stm.get('account_number')
            if returned_acc_id != acc_id or str(returned_acc_no) != str(acc.get('account_number')):
                merged_note = (
                    "NOTE: /statement_merged may swap memo/financial accounts and returns a combined view. "
                    f"Requested id={acc_id} (no={acc.get('account_number')}), got id={returned_acc_id} (no={returned_acc_no})."
                )
            else:
                merged_note = (
                    "NOTE: /statement_merged is a combined view (financial + memo). "
                    "It may not match single-account balances from /accounts/balances by design."
                )
    except Exception:
        merged_note = None

    payload = {
        'account': {
            'id': acc_id,
            'account_number': acc.get('account_number'),
            'name': acc.get('name'),
        },
        'balances': {
            'cash': b.get('cash'),
            'gold_18k': b.get('gold_18k'),
            'gold_21k': b.get('gold_21k'),
            'gold_22k': b.get('gold_22k'),
            'gold_24k': b.get('gold_24k'),
        },
        'statement': {
            'closing_cash': st.get('closing_balance_cash'),
            'closing_gold_norm': st.get('closing_balance_gold_normalized'),
        },
        'statement_merged': {
            'is_merged': stm.get('is_merged'),
            'closing_cash': stm.get('closing_balance_cash'),
            'closing_gold_norm': stm.get('closing_balance_gold_normalized'),
        },
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print("balances_cash", payload['balances']['cash'])
        print("balances_gold_18k", payload['balances']['gold_18k'])
        print("balances_gold_21k", payload['balances']['gold_21k'])
        print("balances_gold_22k", payload['balances']['gold_22k'])
        print("balances_gold_24k", payload['balances']['gold_24k'])
        print("statement_closing_cash", payload['statement']['closing_cash'])
        print("statement_closing_gold_norm", payload['statement']['closing_gold_norm'])
        print("merged_is_merged", payload['statement_merged']['is_merged'])
        print("merged_closing_cash", payload['statement_merged']['closing_cash'])
        print("merged_closing_gold_norm", payload['statement_merged']['closing_gold_norm'])
        if merged_note:
            print(merged_note)

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
