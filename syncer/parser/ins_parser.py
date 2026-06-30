"""/ins API 解析器：将外部合约基础信息转换为 InsInfo 列表。"""

from __future__ import annotations

import logging

from config import config
from models.schemas import InsInfo

logger = logging.getLogger(__name__)


def parse_ins(ins_data: dict) -> list[InsInfo]:
    """解析 /ins 返回的嵌套字典结构为 InsInfo 列表。

    ins_data 结构:
        {品种代码: {"pi": {品种信息}, "ins": {合约代码: {合约信息}}}}

    产品类型由品种级 pi.pt 决定（1=期货, 2=期权, 6=个股期权）。
    """
    records: list[InsInfo] = []

    for product_code, product_data in ins_data.items():
        if not isinstance(product_data, dict):
            continue

        pi = product_data.get("pi", {})
        ins_dict = product_data.get("ins", {})

        # 品种级字段
        underlying_name = str(pi.get("n", ""))
        exchange = str(pi.get("ex", ""))
        product_type = _map_product_type(pi.get("pt", 0))
        contract_multiplier = _safe_int(pi.get("M", 1))
        tick_size = _safe_float(pi.get("t", 0)) / 10000.0

        for ins_code, ins_info in ins_dict.items():
            if not isinstance(ins_info, dict):
                continue

            code = str(ins_info.get("i", ins_code))
            underlying = str(ins_info.get("p", product_code))
            expiry = _format_date(ins_info.get("E", ""))
            list_date = _format_date(ins_info.get("O", ""))

            # 期权类型和行权价从合约代码解析
            option_type, strike = _parse_option_fields(code) if product_type == "option" else ("", 0.0)

            record = InsInfo(
                code=code,
                underlying=underlying,
                underlying_name=underlying_name,
                exchange=exchange,
                product_type=product_type,
                expiry=expiry,
                list_date=list_date,
                option_type=option_type,
                strike=strike,
                contract_multiplier=contract_multiplier,
                tick_size=tick_size,
                main_flag=0,  # 后续 merge 阶段从 price 数据回填
            )
            records.append(record)

    logger.info("Parsed %d contracts from /ins", len(records))
    return records


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _map_product_type(raw_type) -> str:
    """将 /ins 中 pi.pt 字段值映射为 product_type 字符串。

    pt 含义:
        1 → 期货
        2 → 期权
        6 → 个股期权
    """
    try:
        t = int(raw_type)
    except (ValueError, TypeError):
        return "unknown"

    if t in config.option_types:
        return "option"
    if t in config.future_types:
        return "future"
    return "unknown"


def _format_date(raw) -> str:
    """将数字日期格式化为 ISO 日期字符串。

    20261021 → "2026-10-21"
    "" / 0 / None → ""
    """
    if raw is None or raw == "" or raw == 0:
        return ""
    try:
        s = str(int(raw))
        if len(s) == 8:
            return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
    except (ValueError, TypeError):
        pass
    return str(raw)


def _parse_option_fields(code: str) -> tuple[str, float]:
    """从期权合约代码解析 C/P 类型和行权价。

    示例: "IO2409-C-4000" → ("C", 4000.0)
           "IO2409-P-4000" → ("P", 4000.0)
    无法解析时返回 ("", 0.0)。
    """
    try:
        parts = code.split("-")
        if len(parts) >= 3:
            opt_type = parts[-2].upper()
            if opt_type in ("C", "P"):
                strike = float(parts[-1])
                return opt_type, strike
    except (ValueError, IndexError):
        pass
    return "", 0.0


def _safe_int(value) -> int:
    try:
        return int(value)
    except (ValueError, TypeError):
        return 0


def _safe_float(value) -> float:
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0
