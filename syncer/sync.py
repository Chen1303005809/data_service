"""数据同步器：从外部 API 拉取并合并合约数据。

外部 API 实际返回格式（以 data_example/ 中的样例为准）：

/ins:
    {
      "品种代码": {
        "pi": { 品种信息, "pt": 1(期货)/2(期权)/6(个股期权), ... },
        "ins": {
          "合约代码": { "i": "合约代码", "p": "品种", "E": 过期日, "O": 上市日, ... }
        }
      }
    }

/price:
    {
      "fields": ["合约id", "自然日", "交易日", ..., "最新价", "成交量", "昨收", ...],
      "depth": [["AP610", 20260630, ..., 76800000, 14809, 76720000, ...]]
    }
"""

from __future__ import annotations

import asyncio
import logging
from decimal import Decimal

import httpx
import pandas as pd

from cache.redis_client import cache_client
from config import config
from syncer.parser.ins_parser import parse_ins
from syncer.parser.price_parser import get_main_flags, parse_price, reset_main_flags

logger = logging.getLogger(__name__)


async def fetch_data() -> pd.DataFrame | None:
    """实时拉取 /ins 和 /price 并合并为 DataFrame（不写缓存）。

    供缓存不可用时的兜底调用，也供 fetch_and_sync 复用。
    """
    logger.info("Live-fetching data from external APIs...")
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            ins_resp, price_resp = await asyncio_compat_gather(
                client.post(config.ins_api_url),
                client.post(config.price_api_url),
            )

        ins_resp.raise_for_status()
        price_resp.raise_for_status()

        ins_data = ins_resp.json()
        price_data = price_resp.json()

        df = _merge(ins_data, price_data)
        logger.info("Live-fetched %d records", len(df))
        return df

    except httpx.HTTPError as e:
        logger.error("HTTP error fetching external API: %s", e)
        return None
    except Exception:
        logger.exception("Unexpected error during live fetch")
        return None


async def fetch_spot_data() -> pd.DataFrame | None:
    """用 asyncio.to_thread 包裹 akshare 同步调用。

    Returns:
        现货价格 DataFrame（与主表同列结构），失败或禁用时返回 None。
    """
    if not config.spot_enabled:
        logger.info("Spot price fetch disabled by config")
        return None

    try:
        from syncer.parser.spot_parser import fetch_spot_records

        records = await asyncio.to_thread(fetch_spot_records)
        if not records:
            return None
        df = pd.DataFrame(records)
        _ensure_columns(df)
        logger.info("Fetched %d spot price records", len(df))
        return df
    except Exception:
        logger.exception("Failed to fetch spot data")
        return None


async def fetch_contracts_and_sync() -> int:
    """仅拉取 /ins + /price 写入缓存（contracts:latest）。

    Returns:
        记录数。失败时返回 -1。
    """
    df = await fetch_data()
    if df is None or df.empty:
        logger.warning("fetch_contracts_and_sync: no data to cache")
        return -1

    await cache_client.set_df(df, key_override="contracts:latest")
    logger.info("Synced %d contract records to cache", len(df))
    return len(df)


async def fetch_spot_and_sync() -> int:
    """仅拉取 akshare 现货数据写入缓存（spot:latest）。

    Returns:
        记录数。失败时返回 -1。
    """
    df = await fetch_spot_data()
    if df is None or df.empty:
        logger.warning("fetch_spot_and_sync: no spot data to cache")
        return -1

    await cache_client.set_df(df, key_override="spot:latest")
    logger.info("Synced %d spot records to cache", len(df))
    return len(df)


# --- 辅助函数 ---


async def asyncio_compat_gather(*coros):
    """跨 asyncio 版本兼容的 gather。"""
    import asyncio
    return await asyncio.gather(*coros)


def _merge(ins_data: dict, price_data: dict) -> pd.DataFrame:
    """合并 /ins 和 /price 数据为统一 DataFrame。

    合并键: code（合约代码）。
    未匹配到价格的合约，价格字段填默认值。
    """
    # 解析两方数据
    reset_main_flags()
    ins_records = parse_ins(ins_data)
    price_map = parse_price(price_data)
    main_flags = get_main_flags()

    if not ins_records:
        logger.warning("/ins returned no contracts")
        return pd.DataFrame()

    # 构建 flat 行列表（用于 DataFrame 缓存）
    rows: list[dict] = []
    for ins in ins_records:
        code = ins.code
        price = price_map.get(code)

        # 从 price 数据回填 main_flag
        ins.main_flag = main_flags.get(code, 0)

        row = {
            # ins 字段
            "code": ins.code,
            "underlying": ins.underlying,
            "product_type": ins.product_type,
            "type": ins.option_type,        # 保持列名 "type" 用于缓存兼容
            "strike": ins.strike,
            "expiry": ins.expiry,
            "list_date": ins.list_date,
            "underlying_name": ins.underlying_name,
            "exchange": ins.exchange,
            "contract_multiplier": ins.contract_multiplier,
            "tick_size": ins.tick_size,
            "main_flag": ins.main_flag,
            # price 字段
            "last_price": price.last_price if price else Decimal("0"),
            "open": price.open if price else Decimal("0"),
            "high": price.high if price else Decimal("0"),
            "low": price.low if price else Decimal("0"),
            "pre_close": price.pre_close if price else Decimal("0"),
            "pre_settle": price.pre_settle if price else Decimal("0"),
            "settle": price.settle if price else Decimal("0"),
            "avg_price": price.avg_price if price else Decimal("0"),
            "change": price.change if price else Decimal("0"),
            "upper_limit": price.upper_limit if price else Decimal("0"),
            "lower_limit": price.lower_limit if price else Decimal("0"),
            "volume": price.volume if price else 0,
            "turnover": price.turnover if price else Decimal("0"),
            "open_interest": price.open_interest if price else 0,
            "pre_open_interest": price.pre_open_interest if price else 0,
            "bid1_price": price.bid1_price if price else Decimal("0"),
            "bid1_volume": price.bid1_volume if price else 0,
            "ask1_price": price.ask1_price if price else Decimal("0"),
            "ask1_volume": price.ask1_volume if price else 0,
            "trade_date": price.trade_date if price else "",
            "update_time": price.update_time if price else "",
            # fetched_at 存为字符串以便 DataFrame 序列化
            "fetched_at": price.fetched_at.isoformat() if (price and price.fetched_at) else "",
        }
        rows.append(row)

    df = pd.DataFrame(rows)

    # 确保必要列存在
    _ensure_columns(df)

    logger.info("Merged DataFrame: %d rows, columns=%s", len(df), list(df.columns))
    return df


def _ensure_columns(df: pd.DataFrame) -> None:
    """确保 DataFrame 包含所有预期列，缺失的补默认值。"""
    str_cols = [
        "code", "underlying", "product_type", "type", "expiry", "list_date",
        "underlying_name", "exchange", "trade_date", "update_time", "fetched_at",
    ]
    float_cols = [
        "strike", "tick_size", "near_basis", "dom_basis",
    ]
    decimal_cols = [
        "last_price", "open", "high", "low",
        "pre_close", "pre_settle", "settle", "avg_price", "change",
        "upper_limit", "lower_limit", "turnover", "bid1_price", "ask1_price",
    ]
    int_cols = [
        "contract_multiplier", "main_flag", "volume", "open_interest",
        "pre_open_interest", "bid1_volume", "ask1_volume",
    ]

    for col in str_cols:
        if col not in df.columns:
            df[col] = ""
    for col in float_cols:
        if col not in df.columns:
            df[col] = 0.0
    for col in decimal_cols:
        if col not in df.columns:
            df[col] = Decimal("0")
    for col in int_cols:
        if col not in df.columns:
            df[col] = 0
