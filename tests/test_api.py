"""API 集成测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def sample_df() -> pd.DataFrame:
    """构造测试用 DataFrame（含期权和期货）。"""
    return pd.DataFrame(
        [
            {"code": "IO2409-C-4000", "underlying": "IO", "product_type": "option", "type": "C", "strike": 4000.0, "expiry": "2024-09-27", "last_price": 200.0, "change": 5.0, "volume": 10000},
            {"code": "IO2409-P-4000", "underlying": "IO", "product_type": "option", "type": "P", "strike": 4000.0, "expiry": "2024-09-27", "last_price": 80.0, "change": -1.0, "volume": 6000},
            {"code": "IF2409", "underlying": "IF", "product_type": "future", "type": "", "strike": 0.0, "expiry": "2024-09-20", "last_price": 3500.0, "change": 20.0, "volume": 50000},
        ]
    )


@pytest.fixture
def client(sample_df):
    """创建带 mock 缓存的 TestClient。"""
    with patch("cache.redis_client.cache_client.connect", new_callable=AsyncMock), \
         patch("cache.redis_client.cache_client.disconnect", new_callable=AsyncMock), \
         patch("cache.redis_client.cache_client.get_df", new_callable=AsyncMock, return_value=sample_df.copy()), \
         patch("cache.redis_client.cache_client.get_cached_at", new_callable=AsyncMock), \
         patch("cache.redis_client.cache_client.is_stale", new_callable=AsyncMock, return_value=False), \
         patch("config.config.ins_api_url", ""), \
         patch("config.config.price_api_url", ""), \
         patch("config.config.refresh_interval_seconds", 3600):
        from main import app
        client = TestClient(app)
        yield client


class TestOptionsEndpoint:
    """测试 GET /api/options。"""

    def test_get_all_options(self, client):
        resp = client.get("/api/options")
        assert resp.status_code == 200
        data = resp.json()
        # 只返回期权，期货被 product_type 过滤
        assert data["total"] == 2
        assert all(item["product_type"] == "option" for item in data["items"])

    def test_filter_by_type(self, client):
        resp = client.get("/api/options?type=C")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["type"] == "C"

    def test_pagination(self, client):
        resp = client.get("/api/options?limit=1&offset=1")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 1

    def test_invalid_type(self, client):
        resp = client.get("/api/options?type=X")
        assert resp.status_code == 422


class TestFuturesEndpoint:
    """测试 GET /api/futures。"""

    def test_get_all_futures(self, client):
        resp = client.get("/api/futures")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["product_type"] == "future"
        assert data["items"][0]["code"] == "IF2409"

    def test_filter_by_underlying(self, client):
        resp = client.get("/api/futures?underlying=IF")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1

    def test_futures_no_callput(self, client):
        """期货没有 C/P 类型，filter 忽略该参数。"""
        resp = client.get("/api/futures?type=C")
        assert resp.status_code == 200
        data = resp.json()
        # 所有期货 type 为空，所以 C 过滤后结果为 0
        assert data["total"] == 0


class TestHealth:
    """健康检查。"""

    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
