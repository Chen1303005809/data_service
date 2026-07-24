"""现货历史数据 Pydantic 模型。

仿照 kline/models.py 设计，定义现货历史 API 的请求参数与响应结构。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from config import CST


class SpotHistoryQueryParams(BaseModel):
    """现货历史查询参数（来自路由查询参数）。

    date 为锚点日期（默认为今天），days 为从锚点往前追溯的天数。
    - date=latest：先解析为最近交易日，再按 days 往前追溯
    - date=YYYYMMDD：从该日期往前追溯 days 天
    - 只传 days：从今天往前追溯
    - 只传 date：从该日期往前追溯 1 天（即精确单日）
    """

    symbol: str = Field(..., description="品种代码，如 CU、LH、RB", min_length=1)
    days: int = Field(default=14, ge=1, le=60, description="从锚点日期往前追溯的自然日天数。设为 1 则仅查锚点当天")
    date: str | None = Field(
        default=None,
        description="锚点日期 'YYYYMMDD' 或 'latest'（最近交易日）。不传则默认今天。days 决定从此日期往前追溯多少天",
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
