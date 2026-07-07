"""/price API 解析器：将外部行情数据转换为 PriceInfo 字典。"""

from __future__ import annotations

import logging
from datetime import datetime

from config import CST
from models.schemas import PriceInfo

logger = logging.getLogger(__name__)


def parse_price(price_data: dict) -> dict[str, PriceInfo]:
    """解析 /price 返回的表格结构为 code → PriceInfo 的映射。

    price_data 结构:
        {"fields": [...], "depth": [[...], ...]}

    每个 depth 行按 fields 顺序排列。
    """
    fields: list[str] = price_data.get("fields", [])
    depth: list[list] = price_data.get("depth", [])

    # 建立字段名 → 列索引映射
    field_index: dict[str, int] = {name: idx for idx, name in enumerate(fields)}

    fetched_at = datetime.now(CST)

    result: dict[str, PriceInfo] = {}
    for row in depth:
        if not row:
            continue

        code = _get_str(row, field_index, "合约id")

        # 基础行情
        last_price = _get_float(row, field_index, "最新价")
        open_price = _get_float(row, field_index, "开盘价")
        high = _get_float(row, field_index, "最高价")
        low = _get_float(row, field_index, "最低价")
        pre_close = _get_float(row, field_index, "昨收")
        pre_settle = _get_float(row, field_index, "昨结")
        settle = _get_float(row, field_index, "结算价")
        avg_price = _get_float(row, field_index, "均价")

        # 涨跌
        change = (last_price - pre_close) / 10000
        upper_limit = _get_float(row, field_index, "涨停价")
        lower_limit = _get_float(row, field_index, "跌停价")

        # 量仓
        volume = _get_int(row, field_index, "成交量")
        turnover = _get_float(row, field_index, "成交额")
        open_interest = _get_int(row, field_index, "今持仓")
        pre_open_interest = _get_int(row, field_index, "昨持仓")

        # 盘口
        bid1_price = _get_float(row, field_index, "买1价")
        bid1_volume = _get_int(row, field_index, "买1量")
        ask1_price = _get_float(row, field_index, "卖1价")
        ask1_volume = _get_int(row, field_index, "卖1量")

        # 时间
        trade_date = _format_trade_date(row, field_index)
        update_time = _format_update_time(row, field_index)

        # 主力标志
        main_flag = _get_int(row, field_index, "主力标志")

        result[code] = PriceInfo(
            last_price=last_price,
            open=open_price,
            high=high,
            low=low,
            pre_close=pre_close,
            pre_settle=pre_settle,
            settle=settle,
            avg_price=avg_price,
            change=change,
            upper_limit=upper_limit,
            lower_limit=lower_limit,
            volume=volume,
            turnover=turnover,
            open_interest=open_interest,
            pre_open_interest=pre_open_interest,
            bid1_price=bid1_price,
            bid1_volume=bid1_volume,
            ask1_price=ask1_price,
            ask1_volume=ask1_volume,
            trade_date=trade_date,
            update_time=update_time,
            fetched_at=fetched_at,
        )

        # 主力标志不放在 PriceInfo 里（属于合约属性），通过单独的返回值传回
        # 这里用 _main_flags 字典在 merge 阶段回填到 InsInfo
        if not hasattr(parse_price, "_main_flags"):
            parse_price._main_flags: dict[str, int] = {}  # type: ignore[attr-defined]
        parse_price._main_flags[code] = main_flag  # type: ignore[attr-defined]

    logger.info("Parsed %d price records from /price", len(result))
    return result


def get_main_flags() -> dict[str, int]:
    """获取解析出的主力标志映射 {code: main_flag}。"""
    return getattr(parse_price, "_main_flags", {})


def reset_main_flags() -> None:
    """重置主力标志缓存（每次新解析前调用）。"""
    parse_price._main_flags = {}  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _get_str(row: list, field_index: dict[str, int], name: str) -> str:
    idx = field_index.get(name, -1)
    if 0 <= idx < len(row):
        return str(row[idx]) if row[idx] is not None else ""
    return ""


def _get_float(row: list, field_index: dict[str, int], name: str) -> float:
    idx = field_index.get(name, -1)
    if 0 <= idx < len(row):
        try:
            return float(row[idx])
        except (ValueError, TypeError):
            return 0.0
    return 0.0


def _get_int(row: list, field_index: dict[str, int], name: str) -> int:
    idx = field_index.get(name, -1)
    if 0 <= idx < len(row):
        try:
            return int(row[idx])
        except (ValueError, TypeError):
            return 0
    return 0


def _format_trade_date(row: list, field_index: dict[str, int]) -> str:
    """交易日优先，回退自然日，格式化为 YYYY-MM-DD。"""
    for name in ("交易日", "自然日"):
        idx = field_index.get(name, -1)
        if 0 <= idx < len(row):
            raw = row[idx]
            if raw is not None and raw != "" and raw != 0:
                try:
                    s = str(int(raw))
                    if len(s) == 8:
                        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
                except (ValueError, TypeError):
                    pass
    return ""


def _format_update_time(row: list, field_index: dict[str, int]) -> str:
    """更新时间：HHMMSSfff 编码 → HH:MM:SS 字符串。

    编码规则（以 93743000 为例）:
        93743000 // 1000 = 93743 (HHMMSS)
        93743 % 100 = 43 (秒)
        93743 // 100 = 937
        937 % 100 = 37 (分)
        937 // 100 = 9 (时)
        93743000 % 1000 = 0 (毫秒)
        → "09:37:43"
    """
    idx = field_index.get("更新时间", -1)
    if 0 <= idx < len(row):
        raw = row[idx]
        if raw is not None and raw != "" and raw != 0:
            try:
                ts = int(raw)
                ms = ts % 1000
                hhmmss = ts // 1000
                ss = hhmmss % 100
                hhmm = hhmmss // 100
                mm = hhmm % 100
                hh = hhmm // 100
                return f"{hh:02d}:{mm:02d}:{ss:02d}"
            except (ValueError, TypeError):
                pass
    return ""
