"""API 路由：GET /api/options & /api/futures。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query

from config import config
from engine.filter import query as run_query
from models.schemas import ProductType, QueryParams, QueryResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["contracts"])


async def _get_contracts(
    product_type: ProductType,
    code: str | None = Query(default=None, description="合约代码，模糊匹配"),
    underlying: str | None = Query(default=None, description="标的物代码"),
    type: str | None = Query(default=None, pattern="^[CP]$", description="C（看涨）/ P（看跌），仅期权有效"),
    strike_ge: float | None = Query(default=None, description="行权价 >= "),
    strike_le: float | None = Query(default=None, description="行权价 <= "),
    expiry_ge: str | None = Query(default=None, description="到期日 >= (YYYY-MM-DD)"),
    expiry_le: str | None = Query(default=None, description="到期日 <= (YYYY-MM-DD)"),
    price_ge: float | None = Query(default=None, description="最新价 >= "),
    price_le: float | None = Query(default=None, description="最新价 <= "),
    sort: str | None = Query(
        default=None,
        pattern=r"^(price|strike|expiry)_(asc|desc)$",
        description="排序: price_asc/desc, strike_asc/desc, expiry_asc/desc",
    ),
    limit: int = Query(
        default=config.default_limit,
        ge=1,
        le=config.max_limit,
        description="返回条数上限",
    ),
    offset: int = Query(default=0, ge=0, description="分页偏移"),
) -> QueryResponse:
    """通用合约查询。"""
    params = QueryParams(
        code=code,
        underlying=underlying,
        type=type,
        strike_ge=strike_ge,
        strike_le=strike_le,
        expiry_ge=expiry_ge,
        expiry_le=expiry_le,
        price_ge=price_ge,
        price_le=price_le,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    return await run_query(params, product_type=product_type)


@router.get(
    "/api/options",
    response_model=QueryResponse,
    summary="查询期权数据",
)
async def get_options(
    code: str | None = Query(default=None, description="合约代码，模糊匹配"),
    underlying: str | None = Query(default=None, description="标的物代码"),
    type: str | None = Query(default=None, pattern="^[CP]$", description="C（看涨）/ P（看跌）"),
    strike_ge: float | None = Query(default=None, description="行权价 >= "),
    strike_le: float | None = Query(default=None, description="行权价 <= "),
    expiry_ge: str | None = Query(default=None, description="到期日 >= (YYYY-MM-DD)"),
    expiry_le: str | None = Query(default=None, description="到期日 <= (YYYY-MM-DD)"),
    price_ge: float | None = Query(default=None, description="最新价 >= "),
    price_le: float | None = Query(default=None, description="最新价 <= "),
    sort: str | None = Query(
        default=None,
        pattern=r"^(price|strike|expiry)_(asc|desc)$",
        description="排序: price_asc/desc, strike_asc/desc, expiry_asc/desc",
    ),
    limit: int = Query(default=config.default_limit, ge=1, le=config.max_limit, description="返回条数上限"),
    offset: int = Query(default=0, ge=0, description="分页偏移"),
) -> QueryResponse:
    """查询期权数据。"""
    return await _get_contracts(
        product_type=ProductType.OPTION,
        code=code,
        underlying=underlying,
        type=type,
        strike_ge=strike_ge,
        strike_le=strike_le,
        expiry_ge=expiry_ge,
        expiry_le=expiry_le,
        price_ge=price_ge,
        price_le=price_le,
        sort=sort,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/api/futures",
    response_model=QueryResponse,
    summary="查询期货数据",
)
async def get_futures(
    code: str | None = Query(default=None, description="合约代码，模糊匹配"),
    underlying: str | None = Query(default=None, description="标的物代码"),
    strike_ge: float | None = Query(default=None, description="行权价 >= "),
    strike_le: float | None = Query(default=None, description="行权价 <= "),
    expiry_ge: str | None = Query(default=None, description="到期日 >= (YYYY-MM-DD)"),
    expiry_le: str | None = Query(default=None, description="到期日 <= (YYYY-MM-DD)"),
    price_ge: float | None = Query(default=None, description="最新价 >= "),
    price_le: float | None = Query(default=None, description="最新价 <= "),
    sort: str | None = Query(
        default=None,
        pattern=r"^(price|strike|expiry)_(asc|desc)$",
        description="排序: price_asc/desc, strike_asc/desc, expiry_asc/desc",
    ),
    limit: int = Query(default=config.default_limit, ge=1, le=config.max_limit, description="返回条数上限"),
    offset: int = Query(default=0, ge=0, description="分页偏移"),
) -> QueryResponse:
    """查询期货数据。"""
    return await _get_contracts(
        product_type=ProductType.FUTURE,
        code=code,
        underlying=underlying,
        type=None,
        strike_ge=strike_ge,
        strike_le=strike_le,
        expiry_ge=expiry_ge,
        expiry_le=expiry_le,
        price_ge=price_ge,
        price_le=price_le,
        sort=sort,
        limit=limit,
        offset=offset,
    )


@router.get("/health", summary="健康检查")
async def health() -> dict[str, str]:
    """简单健康检查端点。"""
    return {"status": "ok"}
