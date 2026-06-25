"""数据同步器：从外部 API 拉取期权数据并写入缓存。"""

from __future__ import annotations

import logging
from typing import Any

import httpx
import pandas as pd

from cache.redis_client import cache_client
from config import config

logger = logging.getLogger(__name__)


async def fetch_and_sync() -> int:
    """从外部 API 拉取全量数据，转换为 DataFrame 并写入缓存。

    Returns:
        拉取的记录数。失败时返回 -1。
    """
    logger.info("Fetching data from external API...")
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(config.external_api_url)
            resp.raise_for_status()
            data: list[dict[str, Any]] = resp.json()

        if not isinstance(data, list):
            logger.error("External API returned non-list data: %s", type(data))
            return -1

        df = pd.DataFrame(data)
        if df.empty:
            logger.warning("External API returned empty dataset")

        await cache_client.set_df(df)
        logger.info("Synced %d records to cache", len(df))
        return len(df)

    except httpx.HTTPError as e:
        logger.error("HTTP error fetching external API: %s", e)
        return -1
    except Exception:
        logger.exception("Unexpected error during sync")
        return -1
