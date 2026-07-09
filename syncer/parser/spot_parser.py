"""现货价格数据源：从 akshare 拉取期货品种现货价格与基差。

akshare 的 futures_spot_price 返回各期货品种的现货价、近月/主力合约价及基差。
本模块把其输出归一化为与合约主表一致的扁平行结构（product_type="spot"，
code 加 "SPOT_" 前缀），供 syncer 写入 spot:latest 缓存，查询时与合约合并。

⚠️ akshare 真实返回的列名可能随版本变化。若拉取为空或字段缺失，请运行
   `python tests/test_akshare.py` 对照真实列名，并在下方的 _COLUMN_ALIASES
   候选列表里补齐。

⚠️ 现货价格总是取最近一个有数据的交易日（akshare 数据源通常在收盘后才
   更新当日数据，所以默认会从今天向前回退至多 7 天）。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# akshare 可选依赖：未安装时 HAS_AKSHARE=False，现货数据不可用但不影响合约流程
try:
    import akshare as ak
    HAS_AKSHARE = True
except ImportError:  # pragma: no cover - 取决于运行环境
    ak = None  # type: ignore[assignment]
    HAS_AKSHARE = False


# 现货回退拉取的最长跨度（含 7 天可覆盖一个完整长假）
_MAX_FALLBACK_DAYS = 7


# 内部字段 → akshare 候选列名（英文用于测试 mock，中文兼容真实 akshare）
# akshare 1.18.64 真实列：symbol/spot_price/near_contract/near_contract_price/
#   dominant_contract/dominant_contract_price/near_basis/dom_basis/date 等
_COLUMN_ALIASES: dict[str, list[str]] = {
    "symbol": ["symbol", "品种", "代码"],
    "name": ["name", "品种名称", "名称"],
    "spot_price": ["spot_price", "现货价格", "现货价"],
    "near_basis": ["near_basis", "近月基差"],
    "dom_basis": ["dom_basis", "主力基差"],
    "date": ["date", "日期"],
}


def _pick(df, field: str):
    """按候选列名从 DataFrame 取出 field 对应列，找不到返回 None。"""
    for col in _COLUMN_ALIASES.get(field, []):
        if col in df.columns:
            return df[col]
    return None


def _to_float(value, default: float = 0.0) -> float:
    """安全转 float，失败返回默认值。"""
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _fetch_with_fallback():
    """从今天开始向前回退至多 _MAX_FALLBACK_DAYS 天，返回首个非空 DataFrame。

    akshare 的现货数据源通常在收盘后才更新当日数据；遇到周末 / 节假日
    时该日会返回 0 行并打 warning。返回第一个有数据的交易日（最多向前
    回退 7 天，覆盖一个完整长假）。异常或全部为空返回 None。
    """
    today = datetime.now()
    for offset in range(_MAX_FALLBACK_DAYS + 1):
        date_str = (today - timedelta(days=offset)).strftime("%Y%m%d")
        try:
            df = ak.futures_spot_price(date=date_str)
        except Exception:
            logger.exception("Failed to fetch spot price from akshare on %s", date_str)
            return None
        if df is not None and not df.empty:
            if offset > 0:
                logger.info(
                    "Spot price for today is empty, using %s (%d day(s) before) with %d records",
                    date_str, offset, len(df),
                )
            return df
    return None


def fetch_spot_records() -> Optional[list[dict]]:
    """拉取 akshare 现货价格记录。

    Returns:
        归一化记录列表（每条为与合约同列结构的 dict）；无 akshare / 拉取异常 /
        空结果时返回 None。
    """
    if not HAS_AKSHARE:
        logger.warning("akshare not installed, spot price unavailable")
        return None

    df = _fetch_with_fallback()
    if df is None:
        return None

    if df.empty:
        logger.info("akshare returned empty spot price data (all fallback dates empty)")
        return None

    symbol_col = _pick(df, "symbol")
    if symbol_col is None:
        logger.warning("spot price data missing symbol column: %s", list(df.columns))
        return None

    spot_price_col = _pick(df, "spot_price")
    near_basis_col = _pick(df, "near_basis")
    dom_basis_col = _pick(df, "dom_basis")
    name_col = _pick(df, "name")
    date_col = _pick(df, "date")

    records: list[dict] = []
    for idx in range(len(df)):
        symbol = str(symbol_col.iloc[idx]).strip()
        if not symbol:
            continue

        name = str(name_col.iloc[idx]).strip() if name_col is not None else ""
        trade_date = str(date_col.iloc[idx]).strip() if date_col is not None else ""

        records.append({
            # 现货核心字段
            "code": f"SPOT_{symbol}",
            "underlying": symbol,
            "underlying_name": name or symbol,
            "product_type": "spot",
            "last_price": _to_float(spot_price_col.iloc[idx]) if spot_price_col is not None else 0.0,
            "exchange": "中国现货市场",
            "near_basis": _to_float(near_basis_col.iloc[idx]) if near_basis_col is not None else 0.0,
            "dom_basis": _to_float(dom_basis_col.iloc[idx]) if dom_basis_col is not None else 0.0,
            "trade_date": trade_date,
            # 合约专属字段默认值（与 _ensure_columns 一致，保证统一列结构）
            "type": "",
            "strike": 0.0,
            "expiry": "",
            "main_flag": 0,
            "volume": 0,
            "open_interest": 0,
        })

    if not records:
        return None

    logger.info("Parsed %d spot price records from akshare", len(records))
    return records
