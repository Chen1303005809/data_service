"""ins_parser 单元测试：覆盖 pt=2 与 pt=6 都映射为 option。"""

from __future__ import annotations

import pytest

from syncer.parser.ins_parser import _map_product_type, _parse_option_fields, parse_ins


def test_pt2_maps_to_option():
    assert _map_product_type(2) == "option"


def test_pt6_maps_to_option():
    """pt=6 是 HO/IO/MO 等个股期权，必须归入 option。"""
    assert _map_product_type(6) == "option"


def test_pt1_maps_to_future():
    assert _map_product_type(1) == "future"


def test_unknown_pt_falls_back_to_unknown():
    assert _map_product_type(99) == "unknown"
    assert _map_product_type(None) == "unknown"
    assert _map_product_type("abc") == "unknown"


def test_parse_option_fields_io_call():
    assert _parse_option_fields("IO2607-C-5400") == ("C", 5400.0)


def test_parse_option_fields_io_put():
    assert _parse_option_fields("IO2607-P-4000") == ("P", 4000.0)


def test_parse_option_fields_invalid_returns_empty():
    assert _parse_option_fields("IF2607") == ("", 0.0)
    assert _parse_option_fields("") == ("", 0.0)


def test_parse_ins_pt6_options_have_option_type():
    """pt=6 的 IO 合约应被解析为 option，且带 option_type / strike。"""
    ins_data = {
        "IO": {
            "pi": {"n": "沪深300股指期权", "ex": "CFFEX", "pt": 6, "M": 1, "t": 0},
            "ins": {
                "IO2607-C-5400": {"i": "IO2607-C-5400", "p": "IO", "E": 20260717, "O": ""},
                "IO2607-P-5400": {"i": "IO2607-P-5400", "p": "IO", "E": 20260717, "O": ""},
            },
        }
    }
    records = parse_ins(ins_data)
    assert len(records) == 2
    for r in records:
        assert r.product_type == "option"
        assert r.underlying == "IO"
        assert r.option_type in ("C", "P")
        assert r.strike == 5400.0
        assert r.expiry == "2026-07-17"


def test_parse_ins_pt1_futures_have_no_option_fields():
    ins_data = {
        "IF": {
            "pi": {"n": "沪深300期货", "ex": "CFFEX", "pt": 1, "M": 1, "t": 0},
            "ins": {
                "IF2607": {"i": "IF2607", "p": "IF", "E": 20260718, "O": ""},
            },
        }
    }
    records = parse_ins(ins_data)
    assert len(records) == 1
    r = records[0]
    assert r.product_type == "future"
    assert r.option_type == ""
    assert r.strike == 0.0
