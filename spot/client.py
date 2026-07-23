"""现货数据客户端：从 akshare 获取期货品种现货价格与基差，提供统一接口。

该模块的设计仿照 kline/client.py：将一个外部数据源（akshare）封装为
异步友好的客户端，供 api/router.py 和 syncer/sync.py 调用。

akshare 的 futures_spot_price_daily / futures_spot_price_previous 返回
各期货品种的现货价、近月/主力合约价及基差。本模块把其输出归一化为与合约
主表一致的扁平行结构（product_type="spot"，code 加 "SPOT_" 前缀）。

⚠️ 现货价格总是取最近一个有数据的交易日（akshare 数据源通常在收盘后才
   更新当日数据，所以默认会从今天向前回退至多 7 天）。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

from config import CST

logger = logging.getLogger(__name__)

# akshare 可选依赖
try:
    import akshare as ak
    HAS_AKSHARE = True
except ImportError:
    ak = None  # type: ignore[assignment]
    HAS_AKSHARE = False

_MAX_FALLBACK_DAYS = 7

# 内部字段 → akshare 候选列名
_COLUMN_ALIASES: dict[str, list[str]] = {
    "symbol": ["symbol", "品种", "代码", "商品"],
    "name": ["name", "品种名称", "名称"],
    "spot_price": ["spot_price", "现货价格", "现货价"],
    "near_basis": ["near_basis", "近月基差"],
    "dom_basis": ["dom_basis", "主力基差"],
    "date": ["date", "日期"],
}

# 中文商品名 → 品种代码映射（futures_spot_price_previous 兜底时使用）
_COMMODITY_NAME_TO_SYMBOL: dict[str, str] = {
    "铜": "CU", "螺纹钢": "RB", "锌": "ZN", "铝": "AL", "黄金": "AU",
    "线材": "WR", "燃料油": "FU", "天然橡胶": "RU", "铅": "PB", "白银": "AG",
    "石油沥青": "BU", "热轧卷板": "HC", "镍": "NI", "锡": "SN",
    "纸浆": "SP", "不锈钢": "SS", "丁二烯橡胶": "BR",
    "PTA": "TA", "白糖": "SR", "棉花": "CF", "普麦": "PM",
    "菜籽油OI": "OI", "玻璃": "FG", "菜籽粕": "RM",
    "硅铁": "SF", "锰硅": "SM", "甲醇MA": "MA", "棉纱": "CY",
    "尿素": "UR", "纯碱": "SA", "涤纶短纤": "PF",
    "PX": "PX", "烧碱": "SH", "棕榈油": "P",
    "聚氯乙烯": "V", "聚乙烯": "L", "豆一": "A", "豆粕": "M",
    "豆油": "Y", "玉米": "C", "焦炭": "J", "焦煤": "JM",
    "铁矿石": "I", "鸡蛋": "JD", "聚丙烯": "PP", "乙二醇": "EG",
    "苯乙烯": "EB", "液化石油气": "PG", "生猪": "LH",
    "工业硅": "SI", "碳酸锂": "LC", "多晶硅": "PS",
}


# ---------------------------------------------------------------------------
# 内部工具函数
# ---------------------------------------------------------------------------

def _pick(df: pd.DataFrame, field: str) -> pd.Series | None:
    """按候选列名列表从 DataFrame 中取出第一匹配列。"""
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


def _convert_previous(df_prev: pd.DataFrame) -> pd.DataFrame | None:
    """将 futures_spot_price_previous() 的中文列 DataFrame 转为标准英文格式。"""
    rows = []
    for idx in range(len(df_prev)):
        name = str(df_prev.iloc[idx].get("商品", "")).strip()
        symbol = _COMMODITY_NAME_TO_SYMBOL.get(name, "")
        if not symbol:
            logger.warning("Unknown commodity name: %s, skipping", name)
            continue
        try:
            spot_price = float(str(df_prev.iloc[idx].get("现货价格", "0")).replace(",", ""))
        except (ValueError, TypeError):
            spot_price = 0.0
        try:
            dom_price = float(str(df_prev.iloc[idx].get("主力合约价格", "0")).replace(",", ""))
        except (ValueError, TypeError):
            dom_price = 0.0
        dom_code = str(df_prev.iloc[idx].get("主力合约代码", "")).strip()
        dom_basis = float(df_prev.iloc[idx].get("主力合约基差", 0) or 0)
        dom_month = dom_code[:4] if len(dom_code) >= 4 else ""

        rows.append({
            "date": "",
            "symbol": symbol,
            "spot_price": spot_price,
            "near_contract": "",
            "near_contract_price": 0.0,
            "dominant_contract": dom_code,
            "dominant_contract_price": dom_price,
            "near_month": "",
            "dominant_month": dom_month,
            "near_basis": 0.0,
            "dom_basis": dom_basis,
            "near_basis_rate": 0.0,
            "dom_basis_rate": 0.0,
        })
    if not rows:
        return None
    return pd.DataFrame(rows)


def _fetch_with_fallback() -> pd.DataFrame | None:
    """主路径用 futures_spot_price_daily，兜底用 futures_spot_price_previous。"""
    today = datetime.now(CST)

    # 主路径
    for offset in range(_MAX_FALLBACK_DAYS + 1):
        date_str = (today - timedelta(days=offset)).strftime("%Y%m%d")
        try:
            df = ak.futures_spot_price_daily(start_day=date_str, end_day=date_str)
        except Exception:
            logger.exception("Failed to fetch spot daily from akshare on %s", date_str)
            return None
        if df is not None and not df.empty:
            if offset > 0:
                logger.info(
                    "Spot price for today is empty, using %s (%d day(s) before) with %d records",
                    date_str, offset, len(df),
                )
            return df

    # 兜底
    for offset in range(_MAX_FALLBACK_DAYS + 1):
        date_str = (today - timedelta(days=offset)).strftime("%Y%m%d")
        try:
            df_prev = ak.futures_spot_price_previous(date=date_str)
        except Exception:
            logger.exception("Failed to fetch spot previous from akshare on %s", date_str)
            return None
        if df_prev is not None and not df_prev.empty:
            df = _convert_previous(df_prev)
            if offset > 0:
                logger.info(
                    "Spot previous fallback: using %s (%d day(s) before) with %d records",
                    date_str, offset, len(df),
                )
            return df
    return None


# ---------------------------------------------------------------------------
# 公开接口
# ---------------------------------------------------------------------------

def fetch_spot_records() -> Optional[list[dict]]:
    """拉取 akshare 现货价格记录（所有品种最新快照）。

    用于定时同步写入 spot:latest 缓存，供 /api/contracts?product_type=spot 查询。
    """
    if not HAS_AKSHARE:
        logger.warning("akshare not installed, spot price unavailable")
        return None

    df = _fetch_with_fallback()
    if df is None or df.empty:
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
            "code": f"SPOT_{symbol}",
            "underlying": symbol,
            "underlying_name": name or symbol,
            "product_type": "spot",
            "last_price": _to_float(spot_price_col.iloc[idx]) if spot_price_col is not None else 0.0,
            "exchange": "中国现货市场",
            "near_basis": _to_float(near_basis_col.iloc[idx]) if near_basis_col is not None else 0.0,
            "dom_basis": _to_float(dom_basis_col.iloc[idx]) if dom_basis_col is not None else 0.0,
            "trade_date": trade_date,
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


def fetch_spot_history(symbol: str, days: int = 14, date: str | None = None) -> Optional[list[dict]]:
    """获取指定品种的现货历史基差数据。

    两种模式：
    1. date="latest" → 查询最近一个有数据的交易日（精确单日）
    2. date="YYYYMMDD" → 查询指定日期，自动回退最多 5 天
    3. days=N（默认14） → 查询近 N 天连续序列（约 10 个交易日）

    使用 futures_spot_price_daily()，列名为英文，可直接映射。

    Args:
        symbol: 品种代码，如 "CU"、"LH"
        days: 追溯天数（自然日），当 date 参数不传时生效
        date: 精确日期 "YYYYMMDD" 或 "latest"（最近交易日）。传此参数时忽略 days

    Returns:
        按日期升序排列的历史记录列表。单日模式返回 1 条，失败或无数据时返回 None。
    """
    if not HAS_AKSHARE:
        logger.warning("akshare not installed, spot history unavailable")
        return None

    try:
        # ── 精确日期模式 ──
        if date is not None:
            if date.lower() == "latest":
                # 最近交易日，从今天往回找最多 7 天
                end = datetime.now(CST)
                for offset in range(_MAX_FALLBACK_DAYS + 1):
                    ds = (end - timedelta(days=offset)).strftime("%Y%m%d")
                    df = ak.futures_spot_price_daily(
                        start_day=ds, end_day=ds, vars_list=[symbol],
                    )
                    if df is not None and not df.empty:
                        break
                else:
                    # 兜底 previous
                    for offset in range(_MAX_FALLBACK_DAYS + 1):
                        ds = (end - timedelta(days=offset)).strftime("%Y%m%d")
                        df_prev = ak.futures_spot_price_previous(date=ds)
                        if df_prev is not None and not df_prev.empty:
                            df = _convert_previous(df_prev)
                            # 只保留目标品种
                            df = df[df["symbol"] == symbol] if df is not None else None
                            if df is not None and not df.empty:
                                break
                    else:
                        return None
                if df is None or df.empty:
                    return None
                # 只保留目标品种行（daily 模式已指定 vars_list，但 previous 转换后需筛选）
                if "symbol" in df.columns:
                    df = df[df["symbol"] == symbol]
            else:
                # 精确日期 YYYYMMDD
                df = ak.futures_spot_price_daily(
                    start_day=date, end_day=date, vars_list=[symbol],
                )
                if df is None or df.empty:
                    logger.warning("No spot data for %s on %s", symbol, date)
                    return None

        # ── 区间模式（默认） ──
        else:
            end = datetime.now(CST)
            start = end - timedelta(days=days)
            start_str = start.strftime("%Y%m%d")
            end_str = end.strftime("%Y%m%d")
            df = ak.futures_spot_price_daily(
                start_day=start_str, end_day=end_str, vars_list=[symbol],
            )
            if df is None or df.empty:
                logger.warning("No spot history for %s in [%s, %s]", symbol, start_str, end_str)
                return None

        df = df.sort_values("date")
        records: list[dict] = []
        for idx in range(len(df)):
            row = df.iloc[idx]
            records.append({
                "date": str(row.get("date", "")),
                "spot_price": float(row.get("spot_price", 0) or 0),
                "near_contract": str(row.get("near_contract", "")),
                "near_contract_price": float(row.get("near_contract_price", 0) or 0),
                "dominant_contract": str(row.get("dominant_contract", "")),
                "dominant_contract_price": float(row.get("dominant_contract_price", 0) or 0),
                "near_basis": float(row.get("near_basis", 0) or 0),
                "dom_basis": float(row.get("dom_basis", 0) or 0),
                "near_basis_rate": float(row.get("near_basis_rate", 0) or 0),
                "dom_basis_rate": float(row.get("dom_basis_rate", 0) or 0),
            })
        logger.info("Fetched %d history records for %s", len(records), symbol)
        return records
    except Exception:
        logger.exception("Failed to fetch spot history for %s", symbol)
        return None
