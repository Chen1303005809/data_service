"""现货数据专用过滤引擎。"""

from __future__ import annotations

import logging
from datetime import datetime

import pandas as pd

from cache.redis_client import cache_client
from config import CST

logger = logging.getLogger(__name__)

CACHE_KEY_SPOT = "spot:latest"


async def query_spot(
    code: str | None = None,
    price_ge: float | None = None,
    price_le: float | None = None,
    sort: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """查询现货数据，从 spot:latest 缓存读取。

    Returns:
        {
            "total": int,
            "limit": int,
            "offset": int,
            "cached_at": datetime,
            "items": [{
                "code": str,
                "name": str,
                "spot_price": float,
                "near_basis": float,
                "dom_basis": float,
                "trade_date": str,
            }]
        }
    """
    df = await cache_client.get_df(CACHE_KEY_SPOT)
    cached_at = await cache_client.get_cached_at(CACHE_KEY_SPOT) or datetime.now(CST)

    if df is None or df.empty:
        # 兜底：尝试实时拉取
        logger.warning("Spot cache miss, falling back to live fetch")
        from syncer.sync import fetch_spot_and_sync
        cnt = await fetch_spot_and_sync()
        if cnt > 0:
            df = await cache_client.get_df(CACHE_KEY_SPOT)

    if df is None or df.empty:
        return {
            "total": 0,
            "limit": limit,
            "offset": offset,
            "cached_at": cached_at.isoformat(),
            "items": [],
        }

    # 过滤
    if code:
        df = df[df["code"].str.contains(code, case=False, na=False)]

    if price_ge is not None:
        df = df[df["last_price"] >= price_ge]

    if price_le is not None:
        df = df[df["last_price"] <= price_le]

    total_before = len(df)

    # 排序
    _asc = True
    _col = "last_price"
    if sort:
        parts = sort.split("_")
        if len(parts) == 2:
            _col = parts[0]
            _asc = parts[1] == "asc"
    df = df.sort_values(by=_col, ascending=_asc)

    # 分页
    df = df.iloc[offset: offset + limit]

    items = []
    for _, row in df.iterrows():
        items.append({
            "code": str(row.get("code", "")),
            "name": str(row.get("underlying_name", "")),
            "spot_price": float(row.get("last_price", 0)),
            "near_basis": float(row.get("near_basis", 0)),
            "dom_basis": float(row.get("dom_basis", 0)),
            "trade_date": str(row.get("trade_date", "")),
        })

    logger.debug("Spot query: %d → %d results", total_before, len(items))

    return {
        "total": total_before,
        "limit": limit,
        "offset": offset,
        "cached_at": cached_at.isoformat(),
        "items": items,
    }
