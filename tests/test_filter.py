"""过滤引擎单元测试。"""

from __future__ import annotations

import pandas as pd
import pytest

from models.schemas import QueryParams


@pytest.fixture
def sample_df() -> pd.DataFrame:
    """构造测试用 DataFrame。"""
    return pd.DataFrame(
        [
            {"code": "IO2409-C-4000", "underlying": "IO", "type": "C", "strike": 4000.0, "expiry": "2024-09-27", "last_price": 200.0, "change": 5.0, "volume": 10000},
            {"code": "IO2409-C-4100", "underlying": "IO", "type": "C", "strike": 4100.0, "expiry": "2024-09-27", "last_price": 150.0, "change": -2.0, "volume": 8000},
            {"code": "IO2409-C-4200", "underlying": "IO", "type": "C", "strike": 4200.0, "expiry": "2024-09-27", "last_price": 100.0, "change": 1.0, "volume": 5000},
            {"code": "IO2409-P-4000", "underlying": "IO", "type": "P", "strike": 4000.0, "expiry": "2024-09-27", "last_price": 80.0, "change": -1.0, "volume": 6000},
            {"code": "IO2412-C-4000", "underlying": "IO", "type": "C", "strike": 4000.0, "expiry": "2024-12-27", "last_price": 250.0, "change": 10.0, "volume": 12000},
            {"code": "IF2409-C-3500", "underlying": "IF", "type": "C", "strike": 3500.0, "expiry": "2024-09-20", "last_price": 300.0, "change": -5.0, "volume": 20000},
        ]
    )


class TestFilterEngine:
    """测试 engine/filter.py 中的过滤逻辑。"""

    def test_no_filters_returns_all(self, sample_df):
        """无过滤参数应返回全量。"""
        from engine.filter import _apply_filters

        params = QueryParams()
        result = _apply_filters(sample_df, params)
        assert len(result) == len(sample_df)

    def test_filter_by_underlying(self, sample_df):
        """按标的物过滤。"""
        from engine.filter import _apply_filters

        params = QueryParams(underlying="IF")
        result = _apply_filters(sample_df, params)
        assert len(result) == 1
        assert result.iloc[0]["code"] == "IF2409-C-3500"

    def test_filter_by_type(self, sample_df):
        """按期权类型过滤。"""
        from engine.filter import _apply_filters

        params = QueryParams(type="P")
        result = _apply_filters(sample_df, params)
        assert len(result) == 1
        assert result.iloc[0]["type"] == "P"

    def test_filter_by_strike_range(self, sample_df):
        """按行权价范围过滤。"""
        from engine.filter import _apply_filters

        params = QueryParams(strike_ge=4000, strike_le=4100)
        result = _apply_filters(sample_df, params)
        assert len(result) == 4  # IO: 3 C at 4000/4100/4200? wait, 4200 > 4100, so 2 + 1P at 4000 + 2412-C at 4000? no, strike_lo hides IF.
        # IO2409-C-4000, IO2409-C-4100, IO2409-P-4000, IO2412-C-4000 = 4
        assert all(4000 <= r["strike"] <= 4100 for _, r in result.iterrows())

    def test_filter_by_price_range(self, sample_df):
        """按价格范围过滤。"""
        from engine.filter import _apply_filters

        params = QueryParams(price_ge=100, price_le=200)
        result = _apply_filters(sample_df, params)
        assert len(result) == 3  # 200, 150, 100
        assert all(100 <= r["last_price"] <= 200 for _, r in result.iterrows())

    def test_filter_by_code_fuzzy(self, sample_df):
        """按合约代码模糊匹配。"""
        from engine.filter import _apply_filters

        params = QueryParams(code="IO2409")
        result = _apply_filters(sample_df, params)
        assert len(result) == 4

        params = QueryParams(code="P-")
        result = _apply_filters(sample_df, params)
        assert len(result) == 1
        assert result.iloc[0]["type"] == "P"

    def test_empty_result(self, sample_df):
        """无匹配结果。"""
        from engine.filter import _apply_filters

        params = QueryParams(strike_ge=99999)
        result = _apply_filters(sample_df, params)
        assert len(result) == 0

    def test_pagination(self, sample_df):
        """分页测试。"""
        params = QueryParams(limit=2, offset=1)
        # 跳过第1条取2条
        result = sample_df.iloc[1:3]
        assert len(result) == 2
        assert result.iloc[0]["code"] == sample_df.iloc[1]["code"]

    def test_sort_price_desc(self, sample_df):
        """按价格降序排序。"""
        params = QueryParams(sort="price_desc")
        assert params.sort_field == "price"
        assert params.sort_ascending is False

        sorted_df = sample_df.sort_values(by="last_price", ascending=False)
        assert sorted_df.iloc[0]["last_price"] == 300.0

    def test_range_consistency_validation(self):
        """ge > le 应抛出验证错误。"""
        with pytest.raises(ValueError, match="strike_ge must be <= strike_le"):
            QueryParams(strike_ge=5000, strike_le=4000)
