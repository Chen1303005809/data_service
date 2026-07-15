"""合约到期预警：判定查询返回的期货/期权合约时间是否早于当前时间。

K线链路没有 expiry 字段，从 symbol 解析 YYMM；合约链路直接比 expiry 日期。
检测到过期时返回统一中文 warning 文案，由调用方挂到响应里，不阻断查询。
"""

from __future__ import annotations

import re
from datetime import date, datetime

from config import CST

_WARN_TMPL = "合约 {code} 已于 {when} 到期，可能已停止交易，请确认合约代码是否正确"

# 字母前缀 + 紧跟的 4 位数字（YYMM）。期权代码如 IO2509-C-4000 只取第一段 2509。
_SYMBOL_YYMM_RE = re.compile(r"^[A-Za-z_]+(\d{4})")

# 主连后缀（品种名 + 8888），无到期概念
_MAIN_CONTINUOUS_SUFFIX = "8888"


def _today_cst() -> date:
    """当前 CST 日期。封装为函数便于测试 mock。"""
    return datetime.now(CST).date()


def warning_from_expiry(expiry: str, code: str = "") -> str | None:
    """合约查询场景：expiry 为 YYYY-MM-DD，早于今天(CST) → 返回 warning。

    空串、格式异常、未来日期 → None。
    """
    if not expiry:
        return None
    try:
        exp_date = date.fromisoformat(expiry)
    except ValueError:
        return None
    if exp_date >= _today_cst():
        return None
    return _WARN_TMPL.format(code=code, when=expiry)


def warning_from_symbol(symbol: str) -> str | None:
    """K线场景：从 symbol 解析 YYMM，(year, month) < 当前 (year, month) → warning。

    主连 8888 / 解析不到 4 位数字 / 当月或未来月份 → None。
    """
    if not symbol:
        return None
    m = _SYMBOL_YYMM_RE.match(symbol)
    if not m:
        return None
    yymm = m.group(1)
    if yymm == _MAIN_CONTINUOUS_SUFFIX:
        return None
    year = 2000 + int(yymm[:2])
    month = int(yymm[2:4])
    if month < 1 or month > 12:
        return None
    today = _today_cst()
    if (year, month) >= (today.year, today.month):
        return None
    return _WARN_TMPL.format(code=symbol, when=f"{year:04d}-{month:02d}")
