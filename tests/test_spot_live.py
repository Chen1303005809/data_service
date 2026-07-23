import sys, io
import sys; sys.path.insert(0, ".")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from spot.client import fetch_spot_records, fetch_spot_history

r = fetch_spot_records()
print(f'快照: {len(r)} 个品种, 首个: {r[0]["code"]} 现货 {r[0]["last_price"]}')

print('\nLH 历史:')
h = fetch_spot_history('LH')
for row in h:
    print(f"  {row['date']}  现货 {row['spot_price']:>8}  基差 {row['dom_basis']:>+6}")

print('\nCU 历史:')
h2 = fetch_spot_history('CU')
for row in h2:
    print(f"  {row['date']}  现货 {row['spot_price']:>8}  基差 {row['dom_basis']:>+6}")