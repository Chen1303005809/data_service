"""现货专用 API 路由：GET /api/spot。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from config import config
from engine.spot_filter import query_spot

logger = logging.getLogger(__name__)

spot_router = APIRouter(tags=["spot"])


@spot_router.get(
    "/api/spot",
    summary="查询现货价格",
)
async def get_spot(
    code: str | None = Query(default=None, description="品种代码（模糊匹配，如 CU、RB）"),
    price_ge: float | None = Query(default=None, description="现货价格 >= "),
    price_le: float | None = Query(default=None, description="现货价格 <= "),
    sort: str | None = Query(
        default=None,
        pattern=r"^(code|spot_price|near_basis|dom_basis)_(asc|desc)$",
        description="排序: code_asc/desc, spot_price_asc/desc, near_basis_asc/desc, dom_basis_asc/desc",
    ),
    limit: int = Query(default=config.default_limit, ge=1, le=config.max_limit, description="返回条数上限"),
    offset: int = Query(default=0, ge=0, description="分页偏移"),
):
    """查询现货价格数据，返回精简结构。

    只包含：code, name, spot_price, near_basis, dom_basis, trade_date。
    """
    result = await query_spot(
        code=code,
        price_ge=price_ge,
        price_le=price_le,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    return JSONResponse(content=result)
