"""手动探查 akshare futures_spot_price 真实列名的脚本（非自动化测试）。

用于核对 spot_parser._COLUMN_ALIASES 的候选列名是否与真实 akshare 返回一致。
运行：python tests/test_akshare.py
akshare 未安装时打印提示，不影响 pytest 收集。
"""

try:
    import akshare as ak
    HAS_AKSHARE = True
except ImportError:
    ak = None
    HAS_AKSHARE = False

from datetime import datetime


def main():
    if not HAS_AKSHARE:
        print("akshare not installed, cannot probe columns")
        return
    today = datetime.now().strftime("%Y%m%d")
    print(f"Fetching spot data for {today}...")
    df = ak.futures_spot_price(date="20260706")
    print(f"Got {len(df)} commodities")
    print(df.head(10))
    print("\nColumns:", list(df.columns))


if __name__ == "__main__":
    main()
