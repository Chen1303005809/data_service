"""Pydantic 数据模型：请求参数、合约记录、查询响应。"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_serializer, model_validator


class ProductType(str, Enum):
    """产品类型，用于内部路由。"""
    OPTION = "option"
    FUTURE = "future"
    SPOT = "spot"


# ---------------------------------------------------------------------------
# 合约子模型
# ---------------------------------------------------------------------------

class InsInfo(BaseModel):
    """合约基础信息 — 来自 /ins API，全量映射。"""

    code: str                                              # i: 合约代码
    underlying: str                                        # p: 品种代码
    underlying_name: str = ""                              # pi.n: 品种名称
    exchange: str = ""                                     # pi.ex: 交易所
    product_type: str = ""                                 # pi.pt 映射 → "option" / "future"
    expiry: str = ""                                       # E: 到期日 YYYY-MM-DD
    list_date: str = ""                                    # O: 上市日 YYYY-MM-DD
    option_type: str = ""                                  # C/P，从 code 解析，期货为空
    strike: float = 0.0                                    # 行权价，从 code 解析，期货为 0
    contract_multiplier: int = 1                           # pi.M: 合约乘数
    tick_size: float = 0.0                                 # pi.t / 10000: 最小变动价
    main_flag: int = 0                                     # 主力标志：0=普通, 1=主力, 2=次主力（price API 回填）


class PriceInfo(BaseModel):
    """实时行情 — 来自 /price API，全量映射。

    所有价格为实际值（外部 API 原始值 ×10000 为整数，解析时统一 ÷10000）。
    """

    # 基础行情（Decimal 保证金融级精度）
    last_price: Decimal = Decimal("0")      # 最新价
    open: Decimal = Decimal("0")            # 开盘价
    high: Decimal = Decimal("0")            # 最高价
    low: Decimal = Decimal("0")             # 最低价
    pre_close: Decimal = Decimal("0")       # 昨收
    pre_settle: Decimal = Decimal("0")      # 昨结
    settle: Decimal = Decimal("0")          # 结算价
    avg_price: Decimal = Decimal("0")       # 均价
    # 涨跌
    change: Decimal = Decimal("0")          # 涨跌额 = 最新价 - 昨收
    upper_limit: Decimal = Decimal("0")     # 涨停价
    lower_limit: Decimal = Decimal("0")     # 跌停价
    # 量仓
    volume: int = 0                         # 成交量
    turnover: Decimal = Decimal("0")        # 成交额
    open_interest: int = 0                  # 今持仓
    pre_open_interest: int = 0              # 昨持仓
    # 盘口
    bid1_price: Decimal = Decimal("0")      # 买1价
    bid1_volume: int = 0                    # 买1量
    ask1_price: Decimal = Decimal("0")      # 卖1价
    ask1_volume: int = 0                    # 卖1量
    # 时间
    trade_date: str = ""                    # 交易日 YYYY-MM-DD
    update_time: str = ""                   # 交易所行情更新时间
    fetched_at: Optional[datetime] = None   # 服务拉取到价格的时间
    # 现货基差（akshare 现货数据专用）
    near_basis: Decimal = Decimal("0")     # 近月基差 = 现货价 - 近月合约价
    dom_basis: Decimal = Decimal("0")      # 主力基差 = 现货价 - 主力合约价

    # 序列化时 Decimal → float，确保 JSON 输出为数字而非字符串
    @field_serializer(
        "last_price", "open", "high", "low",
        "pre_close", "pre_settle", "settle", "avg_price",
        "change", "upper_limit", "lower_limit",
        "turnover", "bid1_price", "ask1_price",
        "near_basis", "dom_basis",
        when_used="json",
    )
    def _serialize_decimal(self, v: Decimal) -> float:
        return float(v)


class ContractItem(BaseModel):
    """整合后的合约完整信息。"""

    ins: InsInfo
    price: PriceInfo
    # 预留: kline: Optional[KlineInfo] = None


# ---------------------------------------------------------------------------
# 查询参数 & 响应
# ---------------------------------------------------------------------------

class QueryParams(BaseModel):
    """查询参数模型。期权/期货共用。"""

    code: Optional[list[str]] = Field(default=None, description="合约代码列表，模糊匹配（对每个值做 OR 匹配）")
    underlying: Optional[str] = Field(default=None, description="标的物代码")
    option_type: Optional[str] = Field(default=None, description="C（看涨）/ P（看跌），仅期权有效")
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
    main_flag: Optional[int] = Field(default=None, ge=0, le=2, description="主力标志：0=普通, 1=主力, 2=次主力")
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


class QueryResponse(BaseModel):
    """查询响应模型。"""

    total: int
    limit: int
    offset: int
    cached_at: datetime
    stale: bool = False
    items: list[ContractItem]
