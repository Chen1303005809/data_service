"""品种代码大小写归一化。

K线 TCP 服务对 InstrumentID 大小写敏感（如 "ag" 和 "AG" 可能查不到或查到错数据）。
本模块根据 data_example/symbols_dict.json 构建大小写不敏感索引，把用户输入
（"ag"/"AG"/"Ag"/"ag2507"/"AG2507" 等）归一为字典中规范的大小写后再发往后端。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_DICT_PATH = Path(__file__).resolve().parent / "symbols_dict.json"

# 品种代码 → 规范写法。模块加载时构建一次。
_CASE_INSENSITIVE_INDEX: dict[str, str] = {}

# 提取字母前缀（去掉尾部数字），用于匹配 "AP610" → "AP"
_LETTER_PREFIX_RE = re.compile(r"^([A-Za-z_]+)")


def _build_index() -> dict[str, str]:
    """从 symbols_dict.json 加载并构建 {小写 key: 规范 key} 索引。"""
    with _DICT_PATH.open(encoding="utf-8") as f:
        data: dict[str, str] = json.load(f)
    return {k.lower(): k for k in data}


_CASE_INSENSITIVE_INDEX = _build_index()


def normalize_symbol(symbol: str) -> str:
    """把用户输入的品种代码归一为 symbols_dict.json 中的规范大小写。

    匹配规则（按优先级）：
    1. 完整字符串小写后精确匹配 → 返回规范写法（如 "AG" → "AP"，"ag" → "ag"）
    2. 提取字母前缀（如 "AP610" → "AP"），前缀小写后精确匹配 →
       用规范写法重组（"AP610" → "AP610"，"ag2507" → "ag2507"）
    3. 未命中 → 原样返回（让 K线 服务自己报错）

    空字符串原样返回。
    """
    if not symbol:
        return symbol

    # 1. 完整匹配
    canonical = _CASE_INSENSITIVE_INDEX.get(symbol.lower())
    if canonical is not None:
        return canonical

    # 2. 前缀匹配（处理 "ag2507"、"AP610" 等带数字尾部的合约代码）
    m = _LETTER_PREFIX_RE.match(symbol)
    if m:
        prefix = m.group(1)
        canonical_prefix = _CASE_INSENSITIVE_INDEX.get(prefix.lower())
        if canonical_prefix is not None:
            # 复用用户输入的尾部（如数字部分），只替换字母前缀
            return canonical_prefix + symbol[len(prefix):]

    # 3. 未命中，原样返回
    return symbol
