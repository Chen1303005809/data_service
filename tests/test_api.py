"""API 集成测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def sample_df() -> pd.DataFrame:
    """构造测试用 DataFrame（含期权和期货，新字段结构）。"""
    return pd.DataFrame(
        [
            {
                "code": "IO2409-C-4000", "underlying": "IO", "product_type": "option",
                "type": "C", "strike": 4000.0, "expiry": "2024-09-27",
                "last_price": 200.0, "change": 5.0, "volume": 10000,
                "list_date": "", "underlying_name": "", "exchange": "",
                "contract_multiplier": 1, "tick_size": 0.0, "main_flag": 0,
                "open": 0.0, "high": 0.0, "low": 0.0, "pre_close": 0.0,
                "pre_settle": 0.0, "settle": 0.0, "avg_price": 0.0,
                "upper_limit": 0.0, "lower_limit": 0.0, "turnover": 0.0,
                "open_interest": 0, "pre_open_interest": 0,
                "bid1_price": 0.0, "bid1_volume": 0, "ask1_price": 0.0, "ask1_volume": 0,
                "trade_date": "", "update_time": "", "fetched_at": "",
            },
            {
                "code": "IO2409-P-4000", "underlying": "IO", "product_type": "option",
                "type": "P", "strike": 4000.0, "expiry": "2024-09-27",
                "last_price": 80.0, "change": -1.0, "volume": 6000,
                "list_date": "", "underlying_name": "", "exchange": "",
                "contract_multiplier": 1, "tick_size": 0.0, "main_flag": 0,
                "open": 0.0, "high": 0.0, "low": 0.0, "pre_close": 0.0,
                "pre_settle": 0.0, "settle": 0.0, "avg_price": 0.0,
                "upper_limit": 0.0, "lower_limit": 0.0, "turnover": 0.0,
                "open_interest": 0, "pre_open_interest": 0,
                "bid1_price": 0.0, "bid1_volume": 0, "ask1_price": 0.0, "ask1_volume": 0,
                "trade_date": "", "update_time": "", "fetched_at": "",
            },
            {
                "code": "IF2409", "underlying": "IF", "product_type": "future",
                "type": "", "strike": 0.0, "expiry": "2024-09-20",
                "last_price": 3500.0, "change": 20.0, "volume": 50000,
                "list_date": "", "underlying_name": "", "exchange": "",
                "contract_multiplier": 1, "tick_size": 0.0, "main_flag": 0,
                "open": 0.0, "high": 0.0, "low": 0.0, "pre_close": 0.0,
                "pre_settle": 0.0, "settle": 0.0, "avg_price": 0.0,
                "upper_limit": 0.0, "lower_limit": 0.0, "turnover": 0.0,
                "open_interest": 0, "pre_open_interest": 0,
                "bid1_price": 0.0, "bid1_volume": 0, "ask1_price": 0.0, "ask1_volume": 0,
                "trade_date": "", "update_time": "", "fetched_at": "",
            },
        ]
    )


@pytest.fixture
def client(sample_df):
    """创建带 mock 缓存的 TestClient。合约缓存命中，现货缓存为空。"""
    empty_spot = sample_df.iloc[0:0].copy()  # 同列结构的空 DataFrame

    async def _get_df(key: str = "contracts:latest"):
        if key == "spot:latest":
            return empty_spot
        return sample_df.copy()

    with patch("cache.redis_client.cache_client.connect", new_callable=AsyncMock), \
         patch("cache.redis_client.cache_client.disconnect", new_callable=AsyncMock), \
         patch("cache.redis_client.cache_client.get_df", new_callable=AsyncMock, side_effect=_get_df), \
         patch("cache.redis_client.cache_client.get_cached_at", new_callable=AsyncMock), \
         patch("cache.redis_client.cache_client.is_stale", new_callable=AsyncMock, return_value=False), \
         patch("config.config.ins_api_url", ""), \
         patch("config.config.price_api_url", ""), \
         patch("config.config.contracts_refresh_interval_seconds", 3600):
        from main import app
        client = TestClient(app)
        yield client


class TestContractsEndpoint:
    """测试 GET /api/contracts。"""

    def test_default_returns_futures_only(self, client):
        """不传 product_type → 默认仅期货。"""
        resp = client.get("/api/contracts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1  # 仅 IF2409
        assert data["items"][0]["ins"]["product_type"] == "future"

    def test_get_all_contracts(self, client):
        """显式传 option+future → 返回全部合约。"""
        resp = client.get("/api/contracts?product_type=option&product_type=future")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3

    def test_filter_by_product_type_option(self, client):
        resp = client.get("/api/contracts?product_type=option")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert all(item["ins"]["product_type"] == "option" for item in data["items"])

    def test_filter_by_product_type_future(self, client):
        resp = client.get("/api/contracts?product_type=future")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["ins"]["product_type"] == "future"
        assert data["items"][0]["ins"]["code"] == "IF2409"

    def test_filter_by_option_type(self, client):
        resp = client.get("/api/contracts?product_type=option&option_type=C")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["ins"]["option_type"] == "C"

    def test_filter_by_underlying(self, client):
        resp = client.get("/api/contracts?underlying=IF")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["ins"]["underlying"] == "IF"

    def test_pagination(self, client):
        resp = client.get("/api/contracts?product_type=option&product_type=future&limit=1&offset=1")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 1

    def test_filter_by_multi_code(self, client):
        """多 code 查询：OR 逻辑。"""
        resp = client.get("/api/contracts?product_type=option&product_type=future&code=IO2409-C&code=IF2409")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2  # 1 IO2409-C-4000 + 1 IF2409

    def test_invalid_option_type(self, client):
        resp = client.get("/api/contracts?option_type=X")
        assert resp.status_code == 422

    def test_503_when_no_data(self, client, sample_df):
        """缓存空 + 实时拉取失败 → 503。"""
        with patch("cache.redis_client.cache_client.get_df", new_callable=AsyncMock, return_value=None), \
             patch("syncer.sync.fetch_data", new_callable=AsyncMock, return_value=None):
            # 清空缓存
            from cache.redis_client import cache_client
            cache_client._local = {}
            resp = client.get("/api/contracts")
            assert resp.status_code == 503
            assert "unavailable" in resp.json()["detail"].lower()

    def test_nested_response_structure(self, client):
        """验证响应结构为 ins + price 嵌套。"""
        resp = client.get("/api/contracts")
        assert resp.status_code == 200
        data = resp.json()
        item = data["items"][0]
        assert "ins" in item
        assert "price" in item
        assert item["ins"]["code"] is not None
        assert item["price"]["last_price"] is not None

    def test_nested_option_type_field(self, client):
        """验证 option_type 在 ins.option_type 下。"""
        resp = client.get("/api/contracts?product_type=option&option_type=C")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"][0]["ins"]["option_type"] == "C"


class TestHealth:
    """健康检查。"""

    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
