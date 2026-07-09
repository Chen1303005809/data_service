"""API 路由：GET /api/contracts, GET /api/kline。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from config import config
from engine.filter import DataUnavailableError, query as run_query
from kline.client import (
    ConnectionError as KlineConnectionError,
    ConnectionTimeoutError,
    KlineError,
    ProtocolError,
    RemoteError,
    kline_client,
)
from kline.models import KlineQueryParams, KlineResponse
from models.schemas import ProductType, QueryParams, QueryResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["contracts"])


@router.get(
    "/api/contracts",
    response_model=QueryResponse,
    summary="查询合约数据",
)
async def get_contracts(
    product_type: list[ProductType] | None = Query(default=None, description="产品类型筛选（多值 OR）：option / future / spot。不传或为空则仅查期货"),
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


@router.get(
    "/api/kline",
    response_model=KlineResponse,
    summary="查询 K 线历史数据",
)
async def get_kline(params: KlineQueryParams = Depends()) -> KlineResponse:
    """查询期货 K 线历史数据。默认返回日线，最多往前一周。"""
    from datetime import datetime

    date_format = "%Y%m%d"
    start, end = params.resolve_dates()

    # 日期范围校验
    start_dt = datetime.strptime(start, date_format)
    end_dt = datetime.strptime(end, date_format)
    if start_dt > end_dt:
        raise HTTPException(
            status_code=422,
            detail="start_date must not be later than end_date",
        )
    if (end_dt - start_dt).days > 7:
        raise HTTPException(
            status_code=422,
            detail="date range must not exceed 7 days",
        )

    request_body = {
        "GlobalID": 0,
        "ExchangeID": "",
        "InstrumentID": params.symbol,
        "CycleType": params.cycle_type,
        "StartDate": int(start),
        "StartTime": 0,
        "EndDate": int(end),
        "EndTime": 0,
        "KLineType": params.kline_type,
    }
    try:
        raw = await kline_client.fetch(request_body)
        return KlineResponse.model_validate(raw)
    except RemoteError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Remote server error [{e.code}]: {e.message}",
        )
    except ConnectionTimeoutError as e:
        raise HTTPException(status_code=504, detail=str(e))
    except (KlineConnectionError, ProtocolError) as e:
        raise HTTPException(status_code=502, detail=str(e))
    except KlineError as e:
        raise HTTPException(status_code=500, detail=str(e))
