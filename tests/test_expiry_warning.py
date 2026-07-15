"""engine.expiry_warning 到期预警测试。"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

from engine.expiry_warning import warning_from_expiry, warning_from_symbol


# 测试基准"今天"固定为 2026-07-13（CST），避免用例随时间漂移
_FIXED_TODAY = date(2026, 7, 13)


class TestWarningFromExpiry:
    """合约场景：expiry YYYY-MM-DD 比今天。"""

    def setup_method(self) -> None:
        self._patcher = patch("engine.expiry_warning._today_cst", return_value=_FIXED_TODAY)
        self._patcher.start()

    def teardown_method(self) -> None:
        self._patcher.stop()

    def test_expired_returns_warning(self) -> None:
        w = warning_from_expiry("2024-09-27", code="IO2409-C-4000")
        assert w is not None
        assert "IO2409-C-4000" in w
        assert "2024-09-27" in w

    def test_yesterday_expired(self) -> None:
        yesterday = (_FIXED_TODAY - timedelta(days=1)).isoformat()
        assert warning_from_expiry(yesterday, code="x") is not None

    def test_today_not_expired(self) -> None:
        # 到期日 == 今天，按"早于今天"规则不算过期（边界从严）
        assert warning_from_expiry(_FIXED_TODAY.isoformat(), code="x") is None

    def test_future_not_expired(self) -> None:
        future = (_FIXED_TODAY + timedelta(days=30)).isoformat()
        assert warning_from_expiry(future, code="x") is None

    def test_empty_string(self) -> None:
        assert warning_from_expiry("", code="x") is None

    def test_bad_format(self) -> None:
        assert warning_from_expiry("not-a-date", code="x") is None
        assert warning_from_expiry("2024/09/27", code="x") is None

    def test_default_code(self) -> None:
        w = warning_from_expiry("2024-09-27")
        assert w is not None
        # code 默认空串，文案仍可生成
        assert "2024-09-27" in w


class TestWarningFromSymbol:
    """K线场景：从 symbol 解析 YYMM 比年月。"""

    def setup_method(self) -> None:
        self._patcher = patch("engine.expiry_warning._today_cst", return_value=_FIXED_TODAY)
        self._patcher.start()

    def teardown_method(self) -> None:
        self._patcher.stop()

    def test_past_month_contract(self) -> None:
        # 当前 2026-07，2509 是 2025-09 → 过期
        w = warning_from_symbol("ag2509")
        assert w is not None
        assert "ag2509" in w
        assert "2025-09" in w

    def test_option_contract_takes_first_digits(self) -> None:
        # IO2509-C-4000 → 取 2509（行权价 4000 不参与）
        w = warning_from_symbol("IO2509-C-4000")
        assert w is not None
        assert "2025-09" in w

    def test_current_month_not_expired(self) -> None:
        # 2026-07 当月合约仍在交易 → 不预警
        assert warning_from_symbol("ag2607") is None

    def test_future_month_not_expired(self) -> None:
        assert warning_from_symbol("ag2612") is None

    def test_main_continuous_8888_skipped(self) -> None:
        assert warning_from_symbol("ag8888") is None
        assert warning_from_symbol("AP8888") is None

    def test_no_digits_skipped(self) -> None:
        # 纯品种代码无数字尾部
        assert warning_from_symbol("IF") is None
        assert warning_from_symbol("ag") is None

    def test_three_digits_skipped(self) -> None:
        # 非 4 位数字（如 AP610 这种非标准 YYMM）→ 不解析
        assert warning_from_symbol("AP610") is None

    def test_empty_symbol(self) -> None:
        assert warning_from_symbol("") is None

    def test_invalid_month_skipped(self) -> None:
        # YY=25, MM=13 → 非法月份
        assert warning_from_symbol("ag2513") is None
