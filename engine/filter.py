"""过滤引擎：对 DataFrame 进行筛选、排序、分页。"""

from __future__ import annotations

import logging
from datetime import datetime

import pandas as pd

from cache.redis_client import cache_client
from config import CST
from models.schemas import ContractItem, InsInfo, PriceInfo, ProductType, QueryParams, QueryResponse

logger = logging.getLogger(__name__)


async def query(params: QueryParams, product_type: ProductType | None = None) -> QueryResponse:
    """执行查询：缓存优先 → 实时兜底 → 过滤 → 排序 → 分页 → 返回响应。

    1. 优先从 Redis / 本地缓存读取 DataFrame
    2. 缓存不可用或为空时，实时拉取外部 API 兜底，拉取成功后回写缓存
    3. 对数据进行筛选、排序、分页
    4. 返回 QueryResponse
    """
    df = await cache_client.get_df()
    stale = await cache_client.is_stale() or False
    cached_at = await cache_client.get_cached_at() or datetime.now(CST)

    # --- 兜底：缓存不可用时实时拉取 ---
    if df is None or df.empty:
        logger.warning("Cache miss or empty, falling back to live fetch")
        from syncer.sync import fetch_data
        df = await fetch_data()

        if df is not None and not df.empty:
            # 回写缓存（至少写本地），让后续请求受益
            await cache_client.set_df(df)
            cached_at = datetime.now(CST)
            stale = False
            logger.info("Live fetch succeeded, wrote %d records to cache", len(df))

    # --- 最终仍无数据 ---
    if df is None or df.empty:
        raise DataUnavailableError("No data available from cache or live fetch")

    total_before = len(df)

    # 产品类型筛选
    if product_type is not None:
        df = df[df["product_type"] == product_type.value]

    # 通用过滤
    df = _apply_filters(df, params)

    total = len(df)

    # 排序（sort 参数中的字段名映射到 DataFrame 列名）
    _SORT_FIELD_MAP = {
        "price": "last_price",
        "strike": "strike",
        "expiry": "expiry",
    }
    if params.sort_field:
        df_col = _SORT_FIELD_MAP.get(params.sort_field, params.sort_field)
        ascending = params.sort_ascending if params.sort_ascending is not None else True
        df = df.sort_values(by=df_col, ascending=ascending)

    # 分页
    df = df.iloc[params.offset : params.offset + params.limit]

    items = [_row_to_item(row) for _, row in df.iterrows()]

    logger.debug(
        "Query: %d → %d results (product_type=%s, stale=%s)",
        total_before,
        total,
        product_type,
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
        masks = []
        for c in params.code:
            if c:
                masks.append(df["code"].str.contains(c, case=False, na=False))
        if masks:
            combined = masks[0]
            for m in masks[1:]:
                combined = combined | m
            df = df[combined]

    if params.underlying:
        df = df[df["underlying"] == params.underlying]

    if params.option_type:
        # 期权看涨/看跌过滤（期货的 type 列为空，自然被排除）
        df = df[df["type"] == params.option_type]

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


def _row_to_item(row: pd.Series) -> ContractItem:
    """将 DataFrame 行转换为嵌套 ContractItem（InsInfo + PriceInfo）。"""
    return ContractItem(
        ins=InsInfo(
            code=str(row.get("code", "")),
            underlying=str(row.get("underlying", "")),
            underlying_name=str(row.get("underlying_name", "")),
            exchange=str(row.get("exchange", "")),
            product_type=str(row.get("product_type", "")),
            expiry=str(row.get("expiry", "")),
            list_date=str(row.get("list_date", "")),
            option_type=str(row.get("type", "")),
            strike=float(row.get("strike", 0)),
            contract_multiplier=int(row.get("contract_multiplier", 1)),
            tick_size=float(row.get("tick_size", 0)),
            main_flag=int(row.get("main_flag", 0)),
        ),
        price=PriceInfo(
            last_price=row.get("last_price", 0),
            open=row.get("open", 0),
            high=row.get("high", 0),
            low=row.get("low", 0),
            pre_close=row.get("pre_close", 0),
            pre_settle=row.get("pre_settle", 0),
            settle=row.get("settle", 0),
            avg_price=row.get("avg_price", 0),
            change=row.get("change", 0),
            upper_limit=row.get("upper_limit", 0),
            lower_limit=row.get("lower_limit", 0),
            volume=int(row.get("volume", 0)),
            turnover=row.get("turnover", 0),
            open_interest=int(row.get("open_interest", 0)),
            pre_open_interest=int(row.get("pre_open_interest", 0)),
            bid1_price=row.get("bid1_price", 0),
            bid1_volume=int(row.get("bid1_volume", 0)),
            ask1_price=row.get("ask1_price", 0),
            ask1_volume=int(row.get("ask1_volume", 0)),
            trade_date=str(row.get("trade_date", "")),
            update_time=str(row.get("update_time", "")),
            fetched_at=_parse_fetched_at(row.get("fetched_at", "")),
        ),
    )


def _parse_fetched_at(raw) -> datetime | None:
    """从字符串解析 fetched_at。"""
    if not raw or raw == "":
        return None
    try:
        return datetime.fromisoformat(str(raw))
    except (ValueError, TypeError):
        return None


class DataUnavailableError(Exception):
    """数据不可用异常 — 缓存空且实时拉取失败时抛出。"""
    pass
