"""现货价格解析和 API 集成测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest

from models.schemas import ProductType

SAMPLE_SPOT_DATA = pd.DataFrame([
    {
        "symbol": "RB", "spot_price": 3500.0, "dominant_contract_price": 3480.0,
        "near_contract_price": 3490.0, "near_basis": 10.0, "dom_basis": 20.0,
        "date": "20260706",
    },
    {
        "symbol": "CU", "spot_price": 72000.0, "dominant_contract_price": 71800.0,
        "near_contract_price": 71900.0, "near_basis": 100.0, "dom_basis": 200.0,
        "date": "20260706",
    },
])


@pytest.fixture
def mock_akshare():
    """Mock akshare.futures_spot_price 返回值。"""
    with patch("syncer.parser.spot_parser.HAS_AKSHARE", True), \
         patch("syncer.parser.spot_parser.ak") as mock_ak:
        mock_ak.futures_spot_price.return_value = SAMPLE_SPOT_DATA
        yield mock_ak


class TestSpotParser:
    """测试 spot_parser.fetch_spot_records()。"""

    def test_parse_returns_correct_count(self, mock_akshare):
        from syncer.parser.spot_parser import fetch_spot_records
        records = fetch_spot_records()
        assert records is not None
        assert len(records) == 2

    def test_parse_spot_fields(self, mock_akshare):
        from syncer.parser.spot_parser import fetch_spot_records
        records = fetch_spot_records()
        rebar = records[0]
        assert rebar["code"] == "SPOT_RB"
        assert rebar["underlying"] == "RB"
        assert rebar["product_type"] == "spot"
        assert rebar["last_price"] == 3500.0
        assert rebar["exchange"] == "中国现货市场"
        assert rebar["near_basis"] == 10.0
        assert rebar["dom_basis"] == 20.0

    def test_parse_copper(self, mock_akshare):
        from syncer.parser.spot_parser import fetch_spot_records
        records = fetch_spot_records()
        copper = records[1]
        assert copper["code"] == "SPOT_CU"
        assert copper["last_price"] == 72000.0

    def test_contract_specific_fields_default(self, mock_akshare):
        from syncer.parser.spot_parser import fetch_spot_records
        records = fetch_spot_records()
        row = records[0]
        assert row["type"] == ""
        assert row["strike"] == 0.0
        assert row["expiry"] == ""
        assert row["volume"] == 0
        assert row["open_interest"] == 0
        assert row["main_flag"] == 0

    def test_no_akshare_returns_none(self):
        with patch("syncer.parser.spot_parser.HAS_AKSHARE", False):
            from syncer.parser.spot_parser import fetch_spot_records
            assert fetch_spot_records() is None

    def test_akshare_exception_returns_none(self, mock_akshare):
        from syncer.parser.spot_parser import ak
        ak.futures_spot_price.side_effect = Exception("API error")
        from syncer.parser.spot_parser import fetch_spot_records
        records = fetch_spot_records()
        assert records is None

    def test_empty_dataframe_returns_none(self, mock_akshare):
        from syncer.parser.spot_parser import ak
        ak.futures_spot_price.return_value = pd.DataFrame()
        from syncer.parser.spot_parser import fetch_spot_records
        records = fetch_spot_records()
        assert records is None


class TestSpotSync:
    """测试 syncer/sync.py 中现货同步逻辑。"""

    def test_fetch_spot_data_returns_df(self, mock_akshare):
        from syncer.sync import fetch_spot_data
        import asyncio
        spot_df = asyncio.run(fetch_spot_data())
        assert spot_df is not None
        assert len(spot_df) == 2
        assert all(spot_df["product_type"] == "spot")

    def test_fetch_spot_and_sync_writes_to_spot_key(self, mock_akshare):
        """验证现货同步写入 spot:latest 缓存。"""
        with patch("syncer.sync.cache_client.set_df", new_callable=AsyncMock) as mock_set:
            from syncer.sync import fetch_spot_and_sync
            import asyncio
            count = asyncio.run(fetch_spot_and_sync())
            assert count == 2
            mock_set.assert_called_once()
            # 确认使用了 spot:latest key
            assert mock_set.call_args[1].get("key_override") == "spot:latest"


class TestSpotAPI:
    """现货查询集成测试（GET /api/contracts?product_type=spot）。"""

    @pytest.fixture
    def spot_df(self, mock_akshare):
        """构建现货 mock DataFrame。"""
        from syncer.parser.spot_parser import fetch_spot_records
        records = fetch_spot_records()
        return pd.DataFrame(records) if records else pd.DataFrame()

    @pytest.fixture
    def client(self, spot_df):
        """创建 TestClient：合约缓存为空，现货缓存命中。"""
        from datetime import datetime
        from config import CST
        mock_cached_at = datetime.now(CST)
        empty_contracts = spot_df.iloc[0:0].copy()

        async def _get_df(key: str = "contracts:latest"):
            if key == "spot:latest":
                return spot_df.copy()
            return empty_contracts

        with patch("cache.redis_client.cache_client.connect", new_callable=AsyncMock), \
             patch("cache.redis_client.cache_client.disconnect", new_callable=AsyncMock), \
             patch("cache.redis_client.cache_client.get_df", new_callable=AsyncMock, side_effect=_get_df), \
             patch("cache.redis_client.cache_client.get_cached_at", new_callable=AsyncMock, return_value=mock_cached_at), \
             patch("cache.redis_client.cache_client.is_stale", new_callable=AsyncMock, return_value=False), \
             patch("config.config.contracts_refresh_interval_seconds", 3600):
            from main import app
            from fastapi.testclient import TestClient
            client = TestClient(app)
            yield client

    def test_get_all_spot(self, client):
        resp = client.get("/api/contracts?product_type=spot")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2

    def test_filter_by_code(self, client):
        resp = client.get("/api/contracts?product_type=spot&code=CU")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["ins"]["code"] == "SPOT_CU"

    def test_spot_contract_item_structure(self, client):
        """现货返回统一 ContractItem 结构：ins + price 嵌套。"""
        resp = client.get("/api/contracts?product_type=spot&limit=1")
        assert resp.status_code == 200
        item = resp.json()["items"][0]
        assert item["ins"]["code"] == "SPOT_RB"
        assert item["ins"]["product_type"] == "spot"
        # 现货价落在 price.last_price，基差在 price.near_basis/dom_basis
        assert item["price"]["last_price"] == 3500.0
        assert item["price"]["near_basis"] == 10.0
        assert item["price"]["dom_basis"] == 20.0
        assert item["price"]["trade_date"] == "20260706"

    def test_spot_pagination(self, client):
        resp = client.get("/api/contracts?product_type=spot&limit=1&offset=1")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["ins"]["code"] == "SPOT_CU"

    def test_spot_price_filter(self, client):
        resp = client.get("/api/contracts?product_type=spot&price_ge=10000")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["price"]["last_price"] == 72000.0


class TestProductTypeEnum:
    """验证 ProductType 枚举扩展。"""

    def test_spot_member(self):
        assert ProductType.SPOT == "spot"

    def test_all_members(self):
        assert set(ProductType) == {"option", "future", "spot"}
