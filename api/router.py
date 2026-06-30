"""API 路由：GET /api/contracts。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from config import config
from engine.filter import DataUnavailableError, query as run_query
from models.schemas import ProductType, QueryParams, QueryResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["contracts"])


@router.get(
    "/api/contracts",
    response_model=QueryResponse,
    summary="查询合约数据",
)
async def get_contracts(
    product_type: ProductType | None = Query(default=None, description="产品类型筛选: option / future，不传则查全部"),
    code: list[str] | None = Query(default=None, description="合约代码列表，模糊匹配（支持多值 OR）"),
    underlying: str | None = Query(default=None, description="标的物代码"),
    option_type: str | None = Query(default=None, pattern="^[CP]$", description="C（看涨）/ P（看跌），仅期权有效"),
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
    """查询合约数据，支持多维度筛选、排序和分页。"""
    params = QueryParams(
        code=code,
        underlying=underlying,
        option_type=option_type,
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
    try:
        return await run_query(params, product_type=product_type)
    except DataUnavailableError:
        return JSONResponse(
            status_code=503,
            content={"detail": "Data temporarily unavailable. Please retry later."},
        )


@router.get("/health", summary="健康检查")
async def health() -> dict[str, str]:
    """简单健康检查端点。"""
    return {"status": "ok"}
