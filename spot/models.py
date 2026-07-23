"""现货历史数据 Pydantic 模型。

仿照 kline/models.py 设计，定义现货历史 API 的请求参数与响应结构。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from config import CST


class SpotHistoryQueryParams(BaseModel):
    """现货历史查询参数（来自路由查询参数）。

    三种模式：
    - days=N：查询近 N 天连续序列（默认 14 天）
    - date="latest"：精确查询最近一个有数据的交易日
    - date="YYYYMMDD"：精确查询指定日期
    """

    symbol: str = Field(..., description="品种代码，如 CU、LH、RB", min_length=1)
    days: int = Field(default=14, ge=5, le=60, description="追溯自然日天数（约 10 个交易日）。当 date 参数不传时生效")
    date: str | None = Field(
        default=None,
        description="精确日期 'YYYYMMDD' 或 'latest'（最近交易日）。传此参数时忽略 days",
        pattern=r"^(\d{8}|latest)$",
    )


class SpotHistoryItem(BaseModel):
    """单条现货历史数据。"""

    date: str = Field(description="交易日 YYYYMMDD")
    spot_price: float = Field(description="现货价格")
    near_contract: str = Field(description="近月合约代码")
    near_contract_price: float = Field(description="近月合约结算价")
    dominant_contract: str = Field(description="主力合约代码")
    dominant_contract_price: float = Field(description="主力合约结算价")
    near_basis: float = Field(description="近月基差")
    dom_basis: float = Field(description="主力基差")
    near_basis_rate: float = Field(description="近月基差率")
    dom_basis_rate: float = Field(description="主力基差率")


class SpotHistoryResponse(BaseModel):
    """现货历史查询响应。"""

    symbol: str = Field(description="品种代码")
    days: int = Field(description="追溯自然日天数")
    cached_at: str = Field(description="查询时间")
    items: list[SpotHistoryItem] = Field(default_factory=list, description="历史记录列表")
