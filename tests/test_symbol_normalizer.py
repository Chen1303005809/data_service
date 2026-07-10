"""kline.symbol_normalizer 大小写归一测试。"""

from __future__ import annotations

import pytest

from kline.symbol_normalizer import normalize_symbol


class TestExactMatch:
    """完整字符串精确匹配场景。"""

    @pytest.mark.parametrize(
        "user_input,expected",
        [
            # 小写 key 原样返回
            ("ag", "ag"),
            ("cu", "cu"),
            ("a", "a"),
            # 大写 key 归一到小写
            ("AG", "ag"),
            ("CU", "cu"),
            ("A", "a"),
            # 大写 key 归一保持大写
            ("AP", "AP"),
            ("CF", "CF"),
            ("IF", "IF"),
            # 小写 key 输入错误大小写归一到大写
            ("ap", "AP"),
            ("cf", "CF"),
            ("if", "IF"),
            # 混合大小写
            ("Ag", "ag"),
            ("Ap", "AP"),
            ("aG", "ag"),
            # 三个字母 key
            ("APC", "APC"),
            ("apc", "APC"),
            ("Apc", "APC"),
            ("aPC", "APC"),
        ],
    )
    def test_exact_match(self, user_input: str, expected: str) -> None:
        assert normalize_symbol(user_input) == expected


class TestContractCodePrefix:
    """合约代码（带数字尾部）通过字母前缀匹配。"""

    @pytest.mark.parametrize(
        "user_input,expected",
        [
            # 大写前缀 + 数字 → 保持大写前缀
            ("AP610", "AP610"),
            ("CF601", "CF601"),
            ("AP2603", "AP2603"),
            # 小写前缀 + 数字 → 保持小写前缀
            ("ag2507", "ag2507"),
            ("cu2601", "cu2601"),
            ("a2603", "a2603"),
            # 错误大小写前缀 → 归一到规范
            ("ap610", "AP610"),
            ("AP2507", "AP2507"),  # 用户传大写 → 字典中是 AP610 这种
            ("ag610", "ag610"),
            ("AG2507", "ag2507"),
            ("Ag2507", "ag2507"),
            # 三个字母前缀的合约
            ("APC100", "APC100"),
            ("apc100", "APC100"),
            # 短月份代码
            ("T2503", "T2503"),
            ("t2503", "T2503"),
        ],
    )
    def test_contract_code(self, user_input: str, expected: str) -> None:
        assert normalize_symbol(user_input) == expected


class TestNoMatch:
    """未命中场景：原样返回。"""

    @pytest.mark.parametrize(
        "user_input",
        [
            "UNKNOWN_SYMBOL",
            "XYZ",
            "ZZZ9999",
            "some_random_code",
        ],
    )
    def test_unknown_symbol_unchanged(self, user_input: str) -> None:
        assert normalize_symbol(user_input) == user_input


class TestEmpty:
    """边界场景。"""

    def test_empty_string(self) -> None:
        assert normalize_symbol("") == ""

    def test_only_digits(self) -> None:
        # 纯数字无字母前缀，原样返回
        assert normalize_symbol("12345") == "12345"

    def test_underscore_only(self) -> None:
        # 纯下划线，原样返回
        assert normalize_symbol("__") == "__"


class TestSuffixes:
    """带 _o / _f 后缀的 key 不会被误匹配。"""

    def test_a_keine_o_f(self) -> None:
        # "a" 是品种代码；"_o" / "_f" 是后缀品种。不带后缀时只匹配 "a"
        assert normalize_symbol("a") == "a"
        assert normalize_symbol("A") == "a"

    def test_l_keine_f(self) -> None:
        assert normalize_symbol("l") == "l"
        assert normalize_symbol("L") == "l"
