"""过滤引擎：对 DataFrame 进行筛选、排序、分页。"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandas as pd

from cache.redis_client import cache_client
from models.schemas import OptionItem, QueryParams, QueryResponse

logger = logging.getLogger(__name__)


async def query(params: QueryParams) -> QueryResponse:
    """执行查询：从缓存获取数据 → 过滤 → 排序 → 分页 → 返回响应。"""
    df = await cache_client.get_df()
    if df is None or df.empty:
        return QueryResponse(
            total=0,
            limit=params.limit,
            offset=params.offset,
            cached_at=datetime.now(timezone.utc),
            stale=True,
            items=[],
        )

    total_before = len(df)

    # 逐步过滤
    df = _apply_filters(df, params)

    cached_at = await cache_client.get_cached_at() or datetime.now(timezone.utc)
    stale = await cache_client.is_stale() or False

    total = len(df)

    # 排序
    if params.sort_field:
        ascending = params.sort_ascending if params.sort_ascending is not None else True
        df = df.sort_values(by=params.sort_field, ascending=ascending)

    # 分页
    df = df.iloc[params.offset : params.offset + params.limit]

    items = [_row_to_item(row) for _, row in df.iterrows()]

    logger.debug(
        "Query: %d → %d results (stale=%s)",
        total_before,
        total,
        stale,
    )

    return QueryResponse(
        total=total,
        limit=params.limit,
        offset=params.offset,
        cached_at=cached_at,
        stale=stale,
        items=items,
    )


def _apply_filters(df: pd.DataFrame, params: QueryParams) -> pd.DataFrame:
    """逐条件过滤 DataFrame。"""
    if params.code:
        df = df[df["code"].str.contains(params.code, case=False, na=False)]

    if params.underlying:
        df = df[df["underlying"] == params.underlying]

    if params.type:
        df = df[df["type"] == params.type.value]

    if params.strike_ge is not None:
        df = df[df["strike"] >= params.strike_ge]

    if params.strike_le is not None:
        df = df[df["strike"] <= params.strike_le]

    if params.expiry_ge is not None:
        df = df[pd.to_datetime(df["expiry"]) >= pd.Timestamp(params.expiry_ge)]

    if params.expiry_le is not None:
        df = df[pd.to_datetime(df["expiry"]) <= pd.Timestamp(params.expiry_le)]

    if params.price_ge is not None:
        df = df[df["last_price"] >= params.price_ge]

    if params.price_le is not None:
        df = df[df["last_price"] <= params.price_le]

    return df


def _row_to_item(row: pd.Series) -> OptionItem:
    """将 DataFrame 行转换为 OptionItem 模型。"""
    return OptionItem(
        code=str(row.get("code", "")),
        underlying=str(row.get("underlying", "")),
        type=str(row.get("type", "")),
        strike=float(row.get("strike", 0)),
        expiry=str(row.get("expiry", "")),
        last_price=float(row.get("last_price", 0)),
        change=float(row.get("change", 0)),
        volume=int(row.get("volume", 0)),
    )
