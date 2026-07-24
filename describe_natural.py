"""将 K 线 / 期货 / 期权 / 现货数据（dict 格式）解析为自然语言文本描述。

输入为反序列化后的 dict（即 API JSON 响应直接 json.loads 的结果），
输出为纯中文自然语言文本。零值/空字段自动跳过，不存在的字段不输出。

用法:
    import json
    text = describe(json.loads(api_response))
    print(text)

或直接运行:
    python describe_natural.py
"""

from __future__ import annotations

from typing import Any

_CYCLE_LABELS: dict[int, str] = {
    1: "分钟", 2: "小时", 3: "日", 4: "周", 5: "月",
}

_MAIN_FLAG_LABELS: dict[int, str] = {
    0: "普通", 1: "主力", 2: "次主力",
}

_PRODUCT_TYPE_LABELS: dict[str, str] = {
    "future": "期货",
    "option": "期权",
    "spot": "现货",
}


def describe(data: Any, max_items: int = 10) -> str:
    """将 dict 格式的 K线或合约数据转换为自然语言文本描述。

    Args:
        data: API 响应的 dict，使用 alias 字段名（如 "Ins", "data", "items"）。
        max_items: 单条描述的最大条数，超出时只描述前 N 条。

    Returns:
        纯中文自然语言文本。
    """
    if not isinstance(data, dict):
        return "无法识别的数据类型，请传入 dict 格式的数据。"

    if "Ins" in data and "data" in data:
        return _describe_kline(data)

    if "total" in data and "items" in data and isinstance(data.get("items"), list):
        if not data["items"] or (
            isinstance(data["items"][0], dict) and "ins" in data["items"][0]
        ):
            return _describe_contracts(data, max_items)

    if "symbol" in data and "items" in data and isinstance(data.get("items"), list):
        return _describe_spot_history(data)

    return "无法识别的数据类型，请传入 K 线数据、合约数据或现货历史数据。"


def _describe_kline(data: dict) -> str:
    items = data.get("data") or []
    total = len(items)
    ins = data.get("Ins", "")
    cycle = _CYCLE_LABELS.get(data.get("Ty", 3), "日")
    sd = _format_date(data.get("SD", ""))
    ed = _format_date(data.get("ED", ""))

    lines = [f"{ins} 合约{cycle}K线数据，从{sd}到{ed}，共{total}条记录。"]

    if total == 0:
        lines.append("暂无可用数据。")
        return "".join(lines)

    for idx, item in enumerate(items, 1):
        lines.append(_kline_item_text(item, idx))

    lines.append(_kline_summary(items))
    return "".join(lines)


def _kline_item_text(item: dict, idx: int) -> str:
    d = item.get("TiD", "") or item.get("TeD", "")
    t = item.get("T", "")
    o = item.get("O", 0)
    h = item.get("H", 0)
    l = item.get("L", 0)
    c = item.get("C", 0)
    v = item.get("V", 0)
    oi = item.get("OI", 0)

    head = f"第{idx}根K线："
    when = []
    if d:
        when.append(f"日期{_format_date(d)}")
    if t:
        when.append(f"时间{_format_time(t)}")
    if when:
        head += " ".join(when) + "，"
    head += f"开盘{o:.2f} 最高{h:.2f} 最低{l:.2f} 收盘{c:.2f}"

    parts = [head]

    diff = c - o
    if abs(diff) > 0.001 and o != 0:
        if diff > 0:
            parts.append(f"，上涨{diff:.2f}（{diff / o * 100:+.2f}%）")
        else:
            parts.append(f"，下跌{abs(diff):.2f}（{diff / o * 100:+.2f}%）")

    if v:
        parts.append(f"，成交{_human_int(v)}手")
    if oi:
        parts.append(f"，持仓{_human_int(oi)}手")
    parts.append("。")

    return "".join(parts)


def _kline_summary(items: list[dict]) -> str:
    if not items:
        return ""

    highs = [it.get("H", 0) for it in items if it.get("H") is not None]
    lows = [it.get("L", 0) for it in items if it.get("L") is not None]
    total_v = sum(it.get("V", 0) for it in items)
    total_a = sum(it.get("A", 0) for it in items)
    first_date = items[0].get("TiD", "") or items[0].get("TeD", "")
    last_date = items[-1].get("TiD", "") or items[-1].get("TeD", "")

    parts = [f"区间从{_format_date(first_date)}到{_format_date(last_date)}"]
    if highs:
        parts.append(f"，最高价{max(highs):.2f}")
    if lows:
        parts.append(f"最低价{min(lows):.2f}")
    if total_v:
        parts.append(f"，总成交量{_human_int(total_v)}手")
    if total_a:
        parts.append(f"，总成交额{total_a:.2f}")
    parts.append("。")
    return "".join(parts)


def _describe_contracts(data: dict, max_items: int) -> str:
    items = data.get("items") or []
    total = data.get("total", len(items))

    if not items:
        return "暂无符合条件的合约。"

    product_types = {_PRODUCT_TYPE_LABELS.get(it.get("ins", {}).get("product_type", ""), "其他") for it in items}
    type_label = "、".join(sorted(product_types))

    lines = [f"共查询到{total}条{type_label}合约数据。"]

    cached_at = data.get("cached_at")
    if cached_at:
        lines.append(f"数据获取时间：{_format_datetime(cached_at)}。")

    show = items[:max_items]
    for idx, item in enumerate(show, 1):
        lines.append(_contract_item_text(item, idx))

    if total > max_items:
        lines.append(f"（仅展示前{max_items}条，剩余{total - max_items}条已省略）")

    return "".join(lines)


def _contract_item_text(item: dict, idx: int) -> str:
    ins = item.get("ins", {})
    price = item.get("price", {})
    product_type = ins.get("product_type", "")

    main_flag = ins.get("main_flag", 0)
    main_label = _MAIN_FLAG_LABELS.get(main_flag, "普通")
    prefix = f"第{idx}条"
    if main_label != "普通":
        prefix += f"（{main_label}）"
    prefix += "："

    if product_type == "option":
        body = _option_text(ins, price)
    elif product_type == "spot":
        body = _spot_text(ins, price)
    else:
        body = _future_text(ins, price)

    return prefix + body


def _future_text(ins: dict, price: dict) -> str:
    name = _contract_name(ins)
    exchange = ins.get("exchange", "")
    last = price.get("last_price", 0)
    change = price.get("change", 0)
    pre_close = price.get("pre_close", 0)
    volume = price.get("volume", 0)
    open_interest = price.get("open_interest", 0)

    parts = [f"{name}"]
    if exchange:
        parts.append(f"，在{exchange}")
    if last:
        parts.append(f"，最新价{_format_money(last)}元")
    if change and pre_close:
        change_pct = float(change) / float(pre_close) * 100
        if change > 0:
            parts.append(f"，上涨{float(change):.2f}（+{change_pct:.2f}%）")
        elif change < 0:
            parts.append(f"，下跌{abs(float(change)):.2f}（{change_pct:.2f}%）")
    if volume:
        parts.append(f"，成交量{_human_int(volume)}手")
    if open_interest:
        parts.append(f"，持仓量{_human_int(open_interest)}手")
    parts.append("。")
    return "".join(parts)


def _option_text(ins: dict, price: dict) -> str:
    name = _contract_name(ins)
    opt_type = ins.get("option_type", "")
    strike = ins.get("strike", 0)
    expiry = ins.get("expiry", "")
    last = price.get("last_price", 0)
    change = price.get("change", 0)
    pre_close = price.get("pre_close", 0)
    volume = price.get("volume", 0)
    open_interest = price.get("open_interest", 0)

    parts = [f"{name}"]
    if opt_type == "C":
        parts.append(" 看涨期权")
    elif opt_type == "P":
        parts.append(" 看跌期权")
    if strike:
        parts.append(f"，行权价{_format_money(strike)}")
    if expiry:
        parts.append(f"，到期日{expiry}")
    if last:
        parts.append(f"，最新价{_format_money(last)}元")
    if change and pre_close:
        change_pct = float(change) / float(pre_close) * 100
        if change > 0:
            parts.append(f"，上涨{float(change):.2f}（+{change_pct:.2f}%）")
        elif change < 0:
            parts.append(f"，下跌{abs(float(change)):.2f}（{change_pct:.2f}%）")
    if volume:
        parts.append(f"，成交量{_human_int(volume)}手")
    if open_interest:
        parts.append(f"，持仓量{_human_int(open_interest)}手")
    parts.append("。")
    return "".join(parts)


def _spot_text(ins: dict, price: dict) -> str:
    name = _contract_name(ins)
    trade_date = price.get("trade_date", "")
    last = price.get("last_price", 0)
    near_basis = price.get("near_basis", 0)
    dom_basis = price.get("dom_basis", 0)

    parts = [f"{name}"]
    if trade_date:
        parts.append(f"，交易日{trade_date}")
    if last:
        parts.append(f"，最新价{_format_money(last)}元")
    if near_basis:
        sign = "正" if near_basis > 0 else "负"
        parts.append(f"，近月基差{sign}{abs(float(near_basis)):.2f}")
    if dom_basis:
        sign = "正" if dom_basis > 0 else "负"
        parts.append(f"，主力基差{sign}{abs(float(dom_basis)):.2f}")
    parts.append("。")
    return "".join(parts)




def _describe_spot_history(data: dict) -> str:
    """描述现货历史基差数据（/api/spot/history 返回格式）。"""
    symbol = data.get("symbol", "")
    items = data.get("items") or []

    if len(items) == 1:
        lines = [f"{symbol}品种"]
        item = items[0]
        d = item.get("date", "")
        if d:
            lines.append(f"{d}")
        sp = item.get("spot_price", 0)
        if sp:
            lines.append(f"现货价{_format_money(sp)}元")
        dom = item.get("dominant_contract", "")
        dom_p = item.get("dominant_contract_price", 0)
        if dom and dom_p:
            lines.append(f"，主力{dom}@{_format_money(dom_p)}元")
        db = item.get("dom_basis", 0)
        if db:
            sign = "正" if db > 0 else "负"
            lines.append(f"，基差{sign}{abs(float(db)):.2f}")
        lines.append("。")
        return "".join(lines)

    lines = [f"{symbol}品种现货基差历史，共{len(items)}个交易日数据。"]

    if not items:
        lines.append("暂无可用数据。")
        return "".join(lines)

    show = items
    for idx, item in enumerate(show, 1):
        parts = [f"第{idx}个交易日：{item.get('date', '')}"]
        sp = item.get("spot_price", 0)
        if sp:
            parts.append(f"，现货价{_format_money(sp)}元")
        dom = item.get("dominant_contract", "")
        dom_p = item.get("dominant_contract_price", 0)
        if dom and dom_p:
            parts.append(f"，主力合约{dom}@{_format_money(dom_p)}元")
        near = item.get("near_contract", "")
        near_p = item.get("near_contract_price", 0)
        if near and near_p:
            parts.append(f"，近月合约{near}@{_format_money(near_p)}元")
        db = item.get("dom_basis", 0)
        if db:
            sign = "正" if db > 0 else "负"
            parts.append(f"，主力基差{sign}{abs(float(db)):.2f}")
        nb = item.get("near_basis", 0)
        if nb:
            sign = "正" if nb > 0 else "负"
            parts.append(f"，近月基差{sign}{abs(float(nb)):.2f}")
        parts.append("。")
        lines.append("".join(parts))

    # 趋势总结
    spot_prices = [it.get("spot_price", 0) for it in items if it.get("spot_price")]
    dom_bases = [it.get("dom_basis", 0) for it in items if it.get("dom_basis")]
    if len(spot_prices) >= 2:
        first_sp, last_sp = spot_prices[0], spot_prices[-1]
        diff = last_sp - first_sp
        if abs(diff) > 0.01:
            direction = "上涨" if diff > 0 else "下跌"
            lines.append(f"期间现货{direction}{abs(diff):.2f}元，从{_format_money(first_sp)}到{_format_money(last_sp)}。")
    if dom_bases:
        if all(b > 0 for b in dom_bases):
            lines.append("主力基差始终为正（现货升水），期货贴水。")
        elif all(b < 0 for b in dom_bases):
            lines.append("主力基差始终为负（现货贴水），期货升水。")

    return "".join(lines)


def _contract_name(ins: dict) -> str:
    underlying_name = ins.get("underlying_name", "")
    underlying = ins.get("underlying", "")
    code = ins.get("code", "")
    if underlying_name:
        return f"{underlying_name}({code})" if code else underlying_name
    if underlying:
        return f"{underlying}({code})" if code else underlying
    return code


def _human_int(n) -> str:
    n = int(n) if n is not None else 0
    if n < 0:
        return f"-{_human_int(-n)}"
    if n >= 100_000_000:
        return f"{n / 100_000_000:.2f}亿"
    if n >= 10_000:
        return f"{n / 10_000:.1f}万"
    return str(n)


def _format_money(v) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if f == int(f):
        return f"{int(f)}.00"
    return f"{f:.2f}"


def _format_datetime(v) -> str:
    """格式化时间为 'YYYY-MM-DD HH:MM:SS'。接受 ISO 字符串或 datetime。"""
    if not v:
        return ""
    s = str(v).replace("T", " ")
    if "+" in s:
        s = s.split("+", 1)[0]
    elif s.endswith("Z"):
        s = s[:-1]
    return s.strip()


def _format_date(v) -> str:
    """归一为 'YYYY-MM-DD' 带横线。接受 8 位紧凑串、已带横杠串、整数、空值。"""
    if v is None or v == "":
        return ""
    s = str(v).strip()
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return s
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s


def _format_time(v) -> str:
    """把 HHMMSS 紧凑串转成 'HH:MM:SS'。长度不符则原样返回。"""
    if v is None or v == "":
        return ""
    s = str(v).strip()
    if len(s) == 6 and s.isdigit():
        return f"{s[:2]}:{s[2:4]}:{s[4:6]}"
    if len(s) == 4 and s.isdigit():
        return f"{s[:2]}:{s[2:]}"
    return s


if __name__ == "__main__":
    kline_data = {
        "Ins": "AP610",
        "Ty": 3,
        "Req": 123456,
        "GID": 0,
        "EID": "",
        "SD": 20260707,
        "ST": 0,
        "ED": 20260708,
        "ET": 0,
        "data": [
            {
                "TiD": "20260707",
                "TeD": "20260707",
                "T": "093000",
                "O": 7680.0,
                "H": 7720.0,
                "L": 7670.0,
                "C": 7710.0,
                "OI": 120000,
                "V": 5000,
                "VD": 100,
                "A": 38450000.0,
            },
            {
                "TiD": "20260708",
                "TeD": "20260708",
                "T": "093000",
                "O": 7710.0,
                "H": 7730.0,
                "L": 7700.0,
                "C": 7720.0,
                "OI": 121000,
                "V": 3000,
                "VD": 50,
                "A": 23130000.0,
            },
        ],
    }

    contracts_data = {
        "total": 3,
        "limit": 50,
        "offset": 0,
        "cached_at": "2026-07-09T10:30:00",
        "stale": False,
        "items": [
            {
                "ins": {
                    "code": "IF2409",
                    "underlying": "IF",
                    "underlying_name": "沪深300股指期货",
                    "exchange": "中金所",
                    "product_type": "future",
                    "expiry": "2024-09-20",
                    "list_date": "2023-09-21",
                    "option_type": "",
                    "strike": 0.0,
                    "contract_multiplier": 300,
                    "tick_size": 0.2,
                    "main_flag": 1,
                },
                "price": {
                    "last_price": 3500.0,
                    "open": 3498.0,
                    "high": 3510.0,
                    "low": 3485.0,
                    "pre_close": 3520.0,
                    "pre_settle": 3475.0,
                    "settle": 3502.0,
                    "avg_price": 3495.0,
                    "change": -20.0,
                    "upper_limit": 3828.0,
                    "lower_limit": 3132.0,
                    "volume": 50000,
                    "turnover": 5242500000.0,
                    "open_interest": 120000,
                    "pre_open_interest": 118000,
                    "bid1_price": 3499.8,
                    "bid1_volume": 10,
                    "ask1_price": 3500.2,
                    "ask1_volume": 15,
                    "trade_date": "2024-09-19",
                    "update_time": "15:00:00",
                    "fetched_at": "2026-07-09T10:30:00+08:00",
                    "near_basis": 0.0,
                    "dom_basis": 0.0,
                },
            },
            {
                "ins": {
                    "code": "IO2409-C-4000",
                    "underlying": "IO",
                    "underlying_name": "沪深300股指期权",
                    "exchange": "中金所",
                    "product_type": "option",
                    "expiry": "2024-09-27",
                    "list_date": "",
                    "option_type": "C",
                    "strike": 4000.0,
                    "contract_multiplier": 1,
                    "tick_size": 0.0,
                    "main_flag": 0,
                },
                "price": {
                    "last_price": 200.0,
                    "open": 195.0,
                    "high": 205.0,
                    "low": 195.0,
                    "pre_close": 195.0,
                    "pre_settle": 195.0,
                    "settle": 200.0,
                    "avg_price": 200.0,
                    "change": 5.0,
                    "upper_limit": 0.0,
                    "lower_limit": 0.0,
                    "volume": 0,
                    "turnover": 0.0,
                    "open_interest": 0,
                    "pre_open_interest": 0,
                    "bid1_price": 0.0,
                    "bid1_volume": 0,
                    "ask1_price": 0.0,
                    "ask1_volume": 0,
                    "trade_date": "",
                    "update_time": "",
                    "fetched_at": None,
                    "near_basis": 0.0,
                    "dom_basis": 0.0,
                },
            },
            {
                "ins": {
                    "code": "SPOT_RB",
                    "underlying": "RB",
                    "underlying_name": "螺纹钢",
                    "exchange": "",
                    "product_type": "spot",
                    "expiry": "",
                    "list_date": "",
                    "option_type": "",
                    "strike": 0.0,
                    "contract_multiplier": 1,
                    "tick_size": 0.0,
                    "main_flag": 0,
                },
                "price": {
                    "last_price": 3500.0,
                    "open": 0.0,
                    "high": 0.0,
                    "low": 0.0,
                    "pre_close": 0.0,
                    "pre_settle": 0.0,
                    "settle": 0.0,
                    "avg_price": 0.0,
                    "change": 0.0,
                    "upper_limit": 0.0,
                    "lower_limit": 0.0,
                    "volume": 0,
                    "turnover": 0.0,
                    "open_interest": 0,
                    "pre_open_interest": 0,
                    "bid1_price": 0.0,
                    "bid1_volume": 0,
                    "ask1_price": 0.0,
                    "ask1_volume": 0,
                    "trade_date": "2026-07-06",
                    "update_time": "",
                    "fetched_at": None,
                    "near_basis": 10.0,
                    "dom_basis": 20.0,
                },
            },
        ],
    }

    print("=" * 60)
    print("【K线数据描述】")
    print("=" * 60)
    print(describe(kline_data))

    print()
    print("=" * 60)
    print("【合约数据描述】")
    print("=" * 60)
    print(describe(contracts_data))

    print()
    print("=" * 60)
    print("【现货历史基差描述】")
    print("=" * 60)
    spot_history_data = {
        "symbol": "LH",
        "days": 14,
        "cached_at": "2026-07-22T10:30:00",
        "items": [
            {"date": "20260708", "spot_price": 11050.0, "dominant_contract": "lh2609", "dominant_contract_price": 12245.0, "near_contract": "lh2607", "near_contract_price": 10770.0, "near_basis": -280.0, "dom_basis": 1195.0, "near_basis_rate": -0.025, "dom_basis_rate": 0.108},
            {"date": "20260714", "spot_price": 11020.0, "dominant_contract": "lh2609", "dominant_contract_price": 12050.0, "near_contract": "lh2607", "near_contract_price": 10900.0, "near_basis": -120.0, "dom_basis": 1030.0, "near_basis_rate": -0.011, "dom_basis_rate": 0.093},
            {"date": "20260721", "spot_price": 10850.0, "dominant_contract": "lh2609", "dominant_contract_price": 11425.0, "near_contract": "lh2607", "near_contract_price": 10000.0, "near_basis": -850.0, "dom_basis": 575.0, "near_basis_rate": -0.078, "dom_basis_rate": 0.053},
        ],
    }
    print(describe(spot_history_data))
