"""K 线历史数据 Pydantic 模型。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from config import CST


class KlineQueryParams(BaseModel):
    """K 线查询参数（来自路由查询参数）。"""

    symbol: str = Field(..., description="合约代码", min_length=1)
    qrynum: int = Field(
        default=400,
        ge=1,
        description="查询根数（从结束日期往前取 N 根 K 线）",
    )
    end_date: str | None = Field(
        default=None,
        pattern=r"^\d{8}$",
        description="结束日期 YYYYMMDD；不传则默认今天",
    )
    cycle_type: int = Field(
        default=3,
        ge=1,
        le=14,
        description="K 线周期: 1=分, 2=时, 3=日, 4=周, 5=月, …",
    )

    def resolve_end_date(self) -> str:
        """解析实际结束日期（不传则默认今天），返回 YYYYMMDD。"""
        return self.end_date or datetime.now(CST).strftime("%Y%m%d")


class KlineItem(BaseModel):
    """单条 K 线数据。"""

    trade_date: str = Field(alias="TiD", description="交易日")
    natural_date: str = Field(alias="TeD", description="自然日")
    time: str = Field(alias="T", description="时间")
    open: float = Field(alias="O", description="开盘价")
    high: float = Field(alias="H", description="最高价")
    low: float = Field(alias="L", description="最低价")
    close: float = Field(alias="C", description="收盘价")
    open_interest: int = Field(alias="OI", description="持仓量")
    volume: int = Field(alias="V", description="成交量")
    volume_delta: int = Field(alias="VD", description="与上一笔成交量之差")
    amount: float = Field(alias="A", description="成交额")


class KlineResponse(BaseModel):
    """K 线查询响应。"""

    instrument_id: str = Field(alias="Ins")
    cycle_type: int = Field(alias="Ty")
    request_id: int = Field(alias="Req")
    global_id: int = Field(alias="GID")
    exchange_id: str = Field(alias="EID")
    start_date: int = Field(alias="SD")
    start_time: int = Field(alias="ST")
    end_date: int = Field(alias="ED")
    end_time: int = Field(alias="ET")
    data: list[KlineItem]
    warning: str | None = None

    model_config = {"populate_by_name": True}

    @field_validator("data", mode="before")
    @classmethod
    def _ensure_data_list(cls, v: object) -> object:
        """上游偶发返回 data=null/空字符串，归一为空列表避免 ValidationError。"""
        if v is None or v == "":
            return []
        return v
