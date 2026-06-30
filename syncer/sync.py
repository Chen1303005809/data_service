"""数据同步器：从外部 API 双路由拉取并合并合约数据。

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

import logging

import httpx
import pandas as pd

from cache.redis_client import cache_client
from config import config

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


async def fetch_and_sync() -> int:
    """拉取 /ins 和 /price，合并为统一 DataFrame 并写入缓存。

    Returns:
        合并后的记录数。失败时返回 -1。
    """
    df = await fetch_data()
    if df is None or df.empty:
        logger.warning("fetch_and_sync: no data to cache")
        return -1

    await cache_client.set_df(df)
    logger.info("Synced %d records to cache", len(df))
    return len(df)


# --- 辅助函数 ---


async def asyncio_compat_gather(*coros):
    """跨 asyncio 版本兼容的 gather。"""
    import asyncio
    return await asyncio.gather(*coros)


def _parse_ins(ins_data: dict) -> list[dict]:
    """解析 /ins 返回的嵌套字典结构为合约列表。

    ins_data 结构:
        {品种代码: {"pi": {品种信息}, "ins": {合约代码: {合约信息}}}}

    每个合约转换为:
        {code, underlying, product_type, expiry, list_date, type, strike}

    产品类型由品种级 pi.pt 决定（1=期货, 2=期权, 6=个股期权）。
    """
    records: list[dict] = []
    for product_code, product_data in ins_data.items():
        if not isinstance(product_data, dict):
            continue

        pi = product_data.get("pi", {})
        ins_dict = product_data.get("ins", {})

        pt = pi.get("pt", 0)
        product_type = _map_product_type(pt)

        for ins_code, ins_info in ins_dict.items():
            if not isinstance(ins_info, dict):
                continue

            # 过期日格式化：20261021 → "2026-10-21"
            raw_expiry = ins_info.get("E", "")
            expiry = _format_date(raw_expiry)

            # 上市日
            raw_list_date = ins_info.get("O", "")
            list_date = _format_date(raw_list_date)

            record = {
                "code": str(ins_info.get("i", ins_code)),
                "underlying": str(ins_info.get("p", product_code)),
                "product_type": product_type,
                "expiry": expiry,
                "list_date": list_date,
                "type": "",      # 期权 C/P 需从合约代码解析或额外字段获取
                "strike": 0.0,   # 期货无行权价；期权需从合约代码解析
            }
            records.append(record)

    logger.info("Parsed %d contracts from /ins", len(records))
    return records


def _parse_price(price_data: dict) -> dict[str, dict]:
    """解析 /price 返回的表格结构为 code → 价格字段 的映射。

    price_data 结构:
        {"fields": [...], "depth": [[...], ...]}

    每个 depth 行按 fields 顺序排列，返回:
        {code: {last_price, volume, change, ...}}
    """
    fields: list[str] = price_data.get("fields", [])
    depth: list[list] = price_data.get("depth", [])

    # 建立字段名 → 列索引映射
    field_index: dict[str, int] = {name: idx for idx, name in enumerate(fields)}

    # 关键字段索引（以中文名为准）
    code_idx = field_index.get("合约id", 0)
    price_idx = field_index.get("最新价", -1)
    volume_idx = field_index.get("成交量", -1)
    pre_close_idx = field_index.get("昨收", -1)  # 用于计算涨跌额

    result: dict[str, dict] = {}
    for row in depth:
        if not row:
            continue
        code = str(row[code_idx]) if code_idx < len(row) else ""

        # 最新价
        last_price = 0.0
        if price_idx >= 0 and price_idx < len(row):
            try:
                last_price = float(row[price_idx])
            except (ValueError, TypeError):
                last_price = 0.0

        # 成交量
        volume = 0
        if volume_idx >= 0 and volume_idx < len(row):
            try:
                volume = int(row[volume_idx])
            except (ValueError, TypeError):
                volume = 0

        # 涨跌额 = 最新价 - 昨收
        change = 0.0
        if pre_close_idx >= 0 and pre_close_idx < len(row):
            try:
                pre_close = float(row[pre_close_idx])
                change = last_price - pre_close
            except (ValueError, TypeError):
                change = 0.0

        result[code] = {
            "last_price": last_price,
            "volume": volume,
            "change": change,
        }

    logger.info("Parsed %d price records from /price", len(result))
    return result


def _merge(ins_data: dict, price_data: dict) -> pd.DataFrame:
    """合并 /ins 和 /price 数据为统一 DataFrame。

    合并键: code（合约代码）。
    未匹配到价格的合约，价格字段填 0。
    """
    # 解析两方数据
    ins_records = _parse_ins(ins_data)
    price_map = _parse_price(price_data)

    if not ins_records:
        logger.warning("/ins returned no contracts")
        return pd.DataFrame()

    # 合并价格到每条合约记录
    for record in ins_records:
        code = record["code"]
        price_info = price_map.get(code, {})
        record["last_price"] = price_info.get("last_price", 0.0)
        record["volume"] = price_info.get("volume", 0)
        record["change"] = price_info.get("change", 0.0)

    df = pd.DataFrame(ins_records)

    # 确保必要列存在
    for col in ("code", "underlying", "product_type", "type", "strike",
                "expiry", "last_price", "change", "volume"):
        if col not in df.columns:
            df[col] = "" if col in ("code", "underlying", "product_type", "type", "expiry") else 0

    logger.info("Merged DataFrame: %d rows, columns=%s", len(df), list(df.columns))
    return df


def _map_product_type(raw_type) -> str:
    """将 /ins 中 pi.pt 字段值映射为 product_type 字符串。

    pt 含义（以样例注释为准）:
        1 → 期货
        2 → 期权
        6 → 个股期权
    """
    try:
        t = int(raw_type)
    except (ValueError, TypeError):
        return "unknown"

    if t in config.option_types:
        return "option"
    if t in config.future_types:
        return "future"
    return "unknown"


def _format_date(raw) -> str:
    """将数字日期格式化为 ISO 日期字符串。

    20261021 → "2026-10-21"
    "" / 0 / None → ""
    """
    if raw is None or raw == "" or raw == 0:
        return ""
    try:
        s = str(int(raw))
        if len(s) == 8:
            return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
    except (ValueError, TypeError):
        pass
    return str(raw)
