"""API 集成测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def sample_df() -> pd.DataFrame:
    """构造测试用 DataFrame。"""
    return pd.DataFrame(
        [
            {"code": "IO2409-C-4000", "underlying": "IO", "type": "C", "strike": 4000.0, "expiry": "2024-09-27", "last_price": 200.0, "change": 5.0, "volume": 10000},
            {"code": "IO2409-P-4000", "underlying": "IO", "type": "P", "strike": 4000.0, "expiry": "2024-09-27", "last_price": 80.0, "change": -1.0, "volume": 6000},
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
         patch("config.config.external_api_url", ""), \
         patch("config.config.refresh_interval_seconds", 3600):
        # 必须在 mock 生效后导入 app
        from main import app

        client = TestClient(app)
        yield client


class TestAPI:
    """测试 GET /api/options 端点。"""

    def test_get_all(self, client):
        """无参数返回全部。"""
        resp = client.get("/api/options")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["items"]) == 2
        assert data["stale"] is False

    def test_filter_by_type(self, client):
        """按类型过滤。"""
        resp = client.get("/api/options?type=C")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["type"] == "C"

    def test_filter_by_price(self, client):
        """按价格范围过滤。"""
        resp = client.get("/api/options?price_ge=100")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["last_price"] == 200.0

    def test_pagination(self, client):
        """分页。"""
        resp = client.get("/api/options?limit=1&offset=1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["items"]) == 1

    def test_sort(self, client):
        """排序。"""
        resp = client.get("/api/options?sort=price_desc")
        assert resp.status_code == 200
        data = resp.json()
        prices = [item["last_price"] for item in data["items"]]
        assert prices == sorted(prices, reverse=True)

    def test_invalid_type(self, client):
        """非法 type 参数返回 422。"""
        resp = client.get("/api/options?type=X")
        assert resp.status_code == 422

    def test_health(self, client):
        """健康检查端点。"""
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
