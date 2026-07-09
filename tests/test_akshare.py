import akshare as ak
from datetime import datetime

today = datetime.now().strftime("%Y%m%d")
print(f"Fetching spot data for {today}...")
df = ak.futures_spot_price(date="20260706")
print(f"Got {len(df)} commodities")
print(df.head(10))
print("\nColumns:", list(df.columns))