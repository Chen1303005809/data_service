"""过滤引擎单元测试。"""

from __future__ import annotations

import pandas as pd
import pytest

from models.schemas import ProductType, QueryParams


@pytest.fixture
def sample_df() -> pd.DataFrame:
    """构造测试用 DataFrame（含期权和期货）。"""
    return pd.DataFrame(
        [
            {"code": "IO2409-C-4000", "underlying": "IO", "product_type": "option", "type": "C", "strike": 4000.0, "expiry": "2024-09-27", "last_price": 200.0, "change": 5.0, "volume": 10000},
            {"code": "IO2409-C-4100", "underlying": "IO", "product_type": "option", "type": "C", "strike": 4100.0, "expiry": "2024-09-27", "last_price": 150.0, "change": -2.0, "volume": 8000},
            {"code": "IO2409-P-4000", "underlying": "IO", "product_type": "option", "type": "P", "strike": 4000.0, "expiry": "2024-09-27", "last_price": 80.0, "change": -1.0, "volume": 6000},
            {"code": "IF2409", "underlying": "IF", "product_type": "future", "type": "", "strike": 0.0, "expiry": "2024-09-20", "last_price": 3500.0, "change": 20.0, "volume": 50000},
            {"code": "IH2409", "underlying": "IH", "product_type": "future", "type": "", "strike": 0.0, "expiry": "2024-09-20", "last_price": 2400.0, "change": -10.0, "volume": 30000},
        ]
    )


class TestFilterEngine:
    """测试 engine/filter.py 中的过滤逻辑。"""

    def test_no_filters_returns_all(self, sample_df):
        from engine.filter import _apply_filters
        params = QueryParams()
        result = _apply_filters(sample_df, params)
        assert len(result) == len(sample_df)

    def test_product_type_option(self, sample_df):
        """按 product_type=option 过滤。"""
        result = sample_df[sample_df["product_type"] == "option"]
        assert len(result) == 3

    def test_product_type_future(self, sample_df):
        """按 product_type=future 过滤。"""
        result = sample_df[sample_df["product_type"] == "future"]
        assert len(result) == 2

    def test_filter_by_underlying(self, sample_df):
        from engine.filter import _apply_filters
        params = QueryParams(underlying="IF")
        result = _apply_filters(sample_df, params)
        assert len(result) == 1
        assert result.iloc[0]["code"] == "IF2409"

    def test_filter_by_type_call(self, sample_df):
        """期权看涨过滤：期货 type 为空，自然排除。"""
        from engine.filter import _apply_filters
        params = QueryParams(type="C")
        result = _apply_filters(sample_df, params)
        assert len(result) == 2
        assert all(r["type"] == "C" for _, r in result.iterrows())

    def test_filter_by_strike_range(self, sample_df):
        from engine.filter import _apply_filters
        params = QueryParams(strike_ge=4000, strike_le=4100)
        result = _apply_filters(sample_df, params)
        # 期货 strike=0 被排除
        assert len(result) == 3

    def test_filter_by_price_range(self, sample_df):
        from engine.filter import _apply_filters
        params = QueryParams(price_ge=100, price_le=200)
        result = _apply_filters(sample_df, params)
        assert len(result) == 2  # 200, 150

    def test_filter_by_code_fuzzy(self, sample_df):
        from engine.filter import _apply_filters
        params = QueryParams(code="IO2409")
        result = _apply_filters(sample_df, params)
        assert len(result) == 3

    def test_empty_result(self, sample_df):
        from engine.filter import _apply_filters
        params = QueryParams(strike_ge=99999)
        result = _apply_filters(sample_df, params)
        assert len(result) == 0

    def test_range_consistency_validation(self):
        with pytest.raises(ValueError, match="strike_ge must be <= strike_le"):
            QueryParams(strike_ge=5000, strike_le=4000)
