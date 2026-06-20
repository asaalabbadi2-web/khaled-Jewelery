import json
import sys

report_path = sys.argv[1] if len(sys.argv) > 1 else '/app/backend/reports/reconcile_clearing_coverage_sb32_20260620T061612Z.json'
d = json.load(open(report_path, encoding='utf-8'))

ips = d['per_invoice_payment']

over_covered = [ip for ip in ips if ip['remaining'] < -0.01]
print('=== (B) IPs covered beyond their own amount (remaining < 0) ===')
print('count:', len(over_covered))
for ip in over_covered:
    print(f"  IP {ip['invoice_payment_id']:>6} | invoice {ip['invoice_id']} | amount={ip['amount']:>9.2f} "
          f"| covered={ip['covered_by_settlement_line']:>9.2f} | remaining={ip['remaining']:>9.2f} "
          f"| vouchers={ip['covering_voucher_ids']}")

print()
multi_voucher = [ip for ip in ips if len(ip['covering_voucher_ids']) > 1]
print('=== IPs touched by more than one settlement voucher (overlap) ===')
print('count:', len(multi_voucher))
for ip in multi_voucher:
    status = 'OVER' if ip['remaining'] < -0.01 else ('UNDER' if ip['remaining'] > 0.01 else 'OK')
    print(f"  IP {ip['invoice_payment_id']:>6} | amount={ip['amount']:>9.2f} | covered={ip['covered_by_settlement_line']:>9.2f} "
          f"| status={status:5s} | vouchers={ip['covering_voucher_ids']}")
