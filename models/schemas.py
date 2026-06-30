"""Pydantic 数据模型：请求参数、合约记录、查询响应。"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class ProductType(str, Enum):
    """产品类型，用于内部路由。"""
    OPTION = "option"
    FUTURE = "future"


class QueryParams(BaseModel):
    """查询参数模型。期权/期货共用。"""

    code: Optional[list[str]] = Field(default=None, description="合约代码列表，模糊匹配（对每个值做 OR 匹配）")
    underlying: Optional[str] = Field(default=None, description="标的物代码")
    type: Optional[str] = Field(default=None, description="C（看涨）/ P（看跌），仅期权有效")
    strike_ge: Optional[float] = Field(default=None, description="行权价 >= ，仅期权有效")
    strike_le: Optional[float] = Field(default=None, description="行权价 <= ，仅期权有效")
    expiry_ge: Optional[date] = Field(default=None, description="到期日 >= ")
    expiry_le: Optional[date] = Field(default=None, description="到期日 <= ")
    price_ge: Optional[float] = Field(default=None, description="最新价 >= ")
    price_le: Optional[float] = Field(default=None, description="最新价 <= ")
    sort: Optional[str] = Field(
        default=None,
        description="排序: price_asc, price_desc, strike_asc, strike_desc, expiry_asc, expiry_desc",
    )
    limit: int = Field(default=50, ge=1, le=500, description="返回条数上限")
    offset: int = Field(default=0, ge=0, description="分页偏移")

    @model_validator(mode="after")
    def check_range_consistency(self) -> "QueryParams":
        """确保 ge 参数不大于对应的 le 参数。"""
        if self.strike_ge is not None and self.strike_le is not None:
            if self.strike_ge > self.strike_le:
                raise ValueError("strike_ge must be <= strike_le")
        if self.expiry_ge is not None and self.expiry_le is not None:
            if self.expiry_ge > self.expiry_le:
                raise ValueError("expiry_ge must be <= expiry_le")
        if self.price_ge is not None and self.price_le is not None:
            if self.price_ge > self.price_le:
                raise ValueError("price_ge must be <= price_le")
        return self

    @property
    def sort_field(self) -> Optional[str]:
        """从 sort 参数中提取字段名（去掉 _asc/_desc 后缀）。"""
        if self.sort is None:
            return None
        for suffix in ("_asc", "_desc"):
            if self.sort.endswith(suffix):
                return self.sort[: -len(suffix)]
        return None

    @property
    def sort_ascending(self) -> Optional[bool]:
        """从 sort 参数中提取排序方向。"""
        if self.sort is None:
            return None
        return self.sort.endswith("_asc")


class ContractItem(BaseModel):
    """单条合约记录（期权/期货通用）。"""

    code: str
    underlying: str
    product_type: str = ""  # "option" / "future"
    type: str = ""  # 期权: "C"/"P", 期货: 空字符串
    strike: float = 0.0
    expiry: str = ""  # 日期字符串
    last_price: float = 0.0
    change: float = 0.0
    volume: int = 0


class QueryResponse(BaseModel):
    """查询响应模型。"""

    total: int
    limit: int
    offset: int
    cached_at: datetime
    stale: bool = False
    items: list[ContractItem]
