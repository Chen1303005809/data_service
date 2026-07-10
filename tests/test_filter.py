"""过滤引擎单元测试。"""

from __future__ import annotations

import pandas as pd
import pytest

from models.schemas import ProductType, QueryParams


@pytest.fixture
def sample_df() -> pd.DataFrame:
    """构造测试用 DataFrame（含期权和期货，新字段结构）。"""
    base = {
        "list_date": "", "underlying_name": "", "exchange": "",
        "contract_multiplier": 1, "tick_size": 0.0, "main_flag": 0,
        "open": 0.0, "high": 0.0, "low": 0.0, "pre_close": 0.0,
        "pre_settle": 0.0, "settle": 0.0, "avg_price": 0.0,
        "upper_limit": 0.0, "lower_limit": 0.0, "turnover": 0.0,
        "open_interest": 0, "pre_open_interest": 0,
        "bid1_price": 0.0, "bid1_volume": 0, "ask1_price": 0.0, "ask1_volume": 0,
        "trade_date": "", "update_time": "", "fetched_at": "",
    }
    return pd.DataFrame(
        [
            {"code": "IO2409-C-4000", "underlying": "IO", "product_type": "option", "type": "C", "strike": 4000.0, "expiry": "2024-09-27", "last_price": 200.0, "change": 5.0, "volume": 10000, **base},
            {"code": "IO2409-C-4100", "underlying": "IO", "product_type": "option", "type": "C", "strike": 4100.0, "expiry": "2024-09-27", "last_price": 150.0, "change": -2.0, "volume": 8000, **base},
            {"code": "IO2409-P-4000", "underlying": "IO", "product_type": "option", "type": "P", "strike": 4000.0, "expiry": "2024-09-27", "last_price": 80.0, "change": -1.0, "volume": 6000, **base},
            {"code": "IF2409", "underlying": "IF", "product_type": "future", "type": "", "strike": 0.0, "expiry": "2024-09-20", "last_price": 3500.0, "change": 20.0, "volume": 50000, **base},
            {"code": "IH2409", "underlying": "IH", "product_type": "future", "type": "", "strike": 0.0, "expiry": "2024-09-20", "last_price": 2400.0, "change": -10.0, "volume": 30000, **base},
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
        result = sample_df[sample_df["product_type"] == "option"]
        assert len(result) == 3

    def test_product_type_future(self, sample_df):
        result = sample_df[sample_df["product_type"] == "future"]
        assert len(result) == 2

    def test_filter_by_underlying(self, sample_df):
        from engine.filter import _apply_filters
        params = QueryParams(underlying="IF")
        result = _apply_filters(sample_df, params)
        assert len(result) == 1
        assert result.iloc[0]["code"] == "IF2409"

    def test_filter_by_option_type_call(self, sample_df):
        """期权看涨过滤：期货 type 为空，自然排除。"""
        from engine.filter import _apply_filters
        params = QueryParams(option_type="C")
        result = _apply_filters(sample_df, params)
        assert len(result) == 2
        assert all(r["type"] == "C" for _, r in result.iterrows())

    def test_filter_by_strike_range(self, sample_df):
        from engine.filter import _apply_filters
        params = QueryParams(strike_ge=4000, strike_le=4100)
        result = _apply_filters(sample_df, params)
        assert len(result) == 3

    def test_filter_by_price_range(self, sample_df):
        from engine.filter import _apply_filters
        params = QueryParams(price_ge=100, price_le=200)
        result = _apply_filters(sample_df, params)
        assert len(result) == 2

    def test_filter_by_code_fuzzy(self, sample_df):
        from engine.filter import _apply_filters
        params = QueryParams(code=["IO2409"])
        result = _apply_filters(sample_df, params)
        assert len(result) == 3

    def test_filter_by_multi_code(self, sample_df):
        from engine.filter import _apply_filters
        params = QueryParams(code=["IO2409-C", "IF2409"])
        result = _apply_filters(sample_df, params)
        assert len(result) == 3

    def test_filter_by_multi_code_empty_string_ignored(self, sample_df):
        from engine.filter import _apply_filters
        params = QueryParams(code=["", "IO2409", ""])
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


class TestQueryParamsNormalization:
    """QueryParams 字段大小写归一化（LLM 调用方兼容）。"""

    def test_option_type_lowercase_normalized(self):
        assert QueryParams(option_type="c").option_type == "C"
        assert QueryParams(option_type="p").option_type == "P"

    def test_option_type_invalid(self):
        with pytest.raises(ValueError, match="option_type must be C or P"):
            QueryParams(option_type="x")

    def test_underlying_lowercase_normalized(self):
        assert QueryParams(underlying="io").underlying == "IO"
        assert QueryParams(underlying="if").underlying == "IF"

    def test_sort_normalization(self):
        """sort 归一化：接受多种大小写与分隔符写法。"""
        assert QueryParams(sort="PRICE_ASC").sort == "price_asc"
        assert QueryParams(sort="Price_Asc").sort == "price_asc"
        assert QueryParams(sort="price-asc").sort == "price_asc"
        assert QueryParams(sort="PriceASC").sort == "price_asc"
        assert QueryParams(sort="STRIKE_DESC").sort == "strike_desc"
        assert QueryParams(sort="expiry asc").sort == "expiry_asc"

    def test_sort_invalid(self):
        with pytest.raises(ValueError, match="sort must be one of"):
            QueryParams(sort="volume_asc")

    def test_none_fields_unchanged(self):
        p = QueryParams()
        assert p.option_type is None
        assert p.underlying is None
        assert p.sort is None


class TestRowToItem:
    """测试 _row_to_item 嵌套结构组装。"""

    def test_nested_structure(self, sample_df):
        from engine.filter import _row_to_item
        row = sample_df.iloc[0]
        item = _row_to_item(row)
        assert item.ins.code == "IO2409-C-4000"
        assert item.ins.option_type == "C"
        assert item.ins.strike == 4000.0
        assert item.price.last_price == 200.0
        assert item.price.volume == 10000

    def test_future_no_option_type(self, sample_df):
        from engine.filter import _row_to_item
        row = sample_df.iloc[3]  # IF2409
        item = _row_to_item(row)
        assert item.ins.option_type == ""
        assert item.ins.strike == 0.0
        assert item.ins.product_type == "future"
