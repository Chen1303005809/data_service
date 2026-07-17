"""API 路由：GET /api/contracts, GET /api/kline。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
import json
from pydantic import ValidationError

from cache.redis_client import CACHE_KEY_SPOT, cache_client
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
from kline.symbol_normalizer import normalize_symbol
from engine.expiry_warning import warning_from_symbol
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
    option_type: str | None = Query(default=None, description="C（看涨）/ P（看跌），仅期权有效。大小写不敏感"),
    strike_ge: float | None = Query(default=None, description="行权价 >= "),
    strike_le: float | None = Query(default=None, description="行权价 <= "),
    expiry_ge: str | None = Query(default=None, description="到期日 >= (YYYY-MM-DD)"),
    expiry_le: str | None = Query(default=None, description="到期日 <= (YYYY-MM-DD)"),
    price_ge: float | None = Query(default=None, description="最新价 >= "),
    price_le: float | None = Query(default=None, description="最新价 <= "),
    sort: str | None = Query(
        default=None,
        description="排序: price_asc/desc, strike_asc/desc, expiry_asc/desc（大小写与分隔符不敏感）",
    ),
    limit: int = Query(default=config.default_limit, ge=1, le=config.max_limit, description="返回条数上限"),
    offset: int = Query(default=0, ge=0, description="分页偏移"),
) -> QueryResponse:
    """查询合约数据，支持多维度筛选、排序和分页。"""
    try:
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
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=json.loads(e.json()))
    try:
        return await run_query(params, product_type=product_type)
    except DataUnavailableError:
        return JSONResponse(
            status_code=503,
            content={"detail": "Data temporarily unavailable. Please retry later."},
        )


@router.get("/health", summary="健康检查")
async def health() -> JSONResponse:
    """健康检查：合约缓存可用则 200，否则 503。"""
    contracts_ok = await cache_client.exists()
    spot_ok = await cache_client.exists(CACHE_KEY_SPOT)

    scheduler_running: bool | None = None
    try:
        from main import scheduler
        scheduler_running = scheduler.running
    except Exception:
        pass

    checks = {
        "redis": "up" if cache_client.redis_available else "down(local_cache)",
        "contracts_cache": "ok" if contracts_ok else "empty",
        "spot_cache": "ok" if spot_ok else "empty",
        "scheduler": (
            "running" if scheduler_running
            else "stopped" if scheduler_running is False
            else "unknown"
        ),
    }
    healthy = contracts_ok
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={"status": "ok" if healthy else "unavailable", "checks": checks},
    )


@router.get(
    "/api/kline",
    response_model=KlineResponse,
    summary="查询 K 线历史数据",
)
async def get_kline(params: KlineQueryParams = Depends()) -> KlineResponse:
    """查询期货 K 线历史数据。默认返回日线。"""
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

    request_body = {
        "GlobalID": 0,
        "ExchangeID": "",
        "InstrumentID": normalize_symbol(params.symbol),
        "CycleType": params.cycle_type,
        "StartDate": int(start),
        "StartTime": 0,
        "EndDate": int(end),
        "EndTime": 0,
        "KLineType": params.kline_type,
    }
    try:
        raw = await kline_client.fetch(request_body)
        resp = KlineResponse.model_validate(raw)
        resp.warning = warning_from_symbol(normalize_symbol(params.symbol))
        return resp
    except RemoteError as e:
        logger.warning(
            "kline remote error symbol=%s range=%s..%s cycle=%d code=%s msg=%s",
            params.symbol, start, end, params.cycle_type, e.code, e.message,
        )
        raise HTTPException(
            status_code=502,
            detail=f"Remote server error [{e.code}]: {e.message}",
        )
    except ConnectionTimeoutError as e:
        logger.error(
            "kline timeout symbol=%s range=%s..%s cycle=%d err=%s",
            params.symbol, start, end, params.cycle_type, e,
        )
        raise HTTPException(status_code=504, detail=str(e))
    except (KlineConnectionError, ProtocolError) as e:
        logger.error(
            "kline %s symbol=%s range=%s..%s cycle=%d err=%s",
            type(e).__name__, params.symbol, start, end, params.cycle_type, e,
        )
        raise HTTPException(status_code=502, detail=str(e))
    except KlineError as e:
        logger.error(
            "kline %s symbol=%s range=%s..%s cycle=%d err=%s",
            type(e).__name__, params.symbol, start, end, params.cycle_type, e,
        )
        raise HTTPException(status_code=500, detail=str(e))
