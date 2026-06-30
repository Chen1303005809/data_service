"""Redis 客户端封装：DataFrame 的存储与读取。"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandas as pd
import redis.asyncio as aioredis

from config import config

logger = logging.getLogger(__name__)

CACHE_KEY_LATEST = "contracts:latest"
TEMP_KEY_PREFIX = "contracts:temp:"


class CacheClient:
    """Redis 缓存客户端，管理 DataFrame 的序列化存储。

    同时维护一个进程内 local_cache 用于 Redis 不可用时的降级。
    """

    def __init__(self) -> None:
        self._redis: aioredis.Redis | None = None
        self._local_df: pd.DataFrame | None = None
        self._local_cached_at: datetime | None = None

    async def connect(self) -> None:
        """建立 Redis 连接池。"""
        try:
            self._redis = aioredis.from_url(
                config.redis_url,
                decode_responses=False,
            )
            await self._redis.ping()
            logger.info("Redis connected: %s", config.redis_url)
        except Exception:
            logger.warning(
                "Redis unavailable at %s, will use local cache fallback",
                config.redis_url,
            )
            self._redis = None

    async def disconnect(self) -> None:
        """关闭 Redis 连接。"""
        if self._redis:
            await self._redis.close()
            self._redis = None

    # ---- 读取 ----

    async def get_df(self) -> pd.DataFrame | None:
        """获取缓存的 DataFrame（优先 Redis，回退本地）。"""
        if self._redis:
            try:
                data = await self._redis.get(CACHE_KEY_LATEST)
                if data:
                    return pd.read_msgpack(data)
            except Exception:
                logger.exception("Failed to read from Redis, falling back to local")

        if self._local_df is not None:
            return self._local_df.copy()
        return None

    async def get_cached_at(self) -> datetime | None:
        """获取缓存的时间戳（优先 Redis 的 TTL 推算，回退本地）。"""
        if self._redis:
            try:
                ttl = await self._redis.ttl(CACHE_KEY_LATEST)
                if ttl > 0:
                    return datetime.now(timezone.utc).replace(
                        microsecond=0
                    )  # 无法精确还原，标记为当前
            except Exception:
                pass

        return self._local_cached_at

    async def is_stale(self) -> bool | None:
        """判断缓存是否过期（TTL 耗尽）。None 表示无法判断。"""
        if self._redis:
            try:
                ttl = await self._redis.ttl(CACHE_KEY_LATEST)
                if ttl == -2:  # key 不存在
                    return None
                return ttl <= 0
            except Exception:
                pass
        return None

    # ---- 写入 ----

    async def set_df(self, df: pd.DataFrame) -> None:
        """写入 DataFrame 到 Redis + 本地缓存。

        使用临时 key + RENAME 保证原子替换。
        """
        now = datetime.now(timezone.utc)
        payload = df.to_msgpack()

        # 更新本地缓存（始终成功）
        self._local_df = df.copy()
        self._local_cached_at = now

        # 写入 Redis
        if self._redis:
            try:
                temp_key = f"{TEMP_KEY_PREFIX}{int(now.timestamp())}"
                await self._redis.set(temp_key, payload, ex=config.cache_ttl_seconds)
                await self._redis.rename(temp_key, CACHE_KEY_LATEST)
                logger.info("Cache refreshed: %d rows, TTL=%ds", len(df), config.cache_ttl_seconds)
            except Exception:
                logger.exception("Failed to write cache to Redis (local cache updated)")

    @property
    def redis_available(self) -> bool:
        """Redis 是否当前可用。"""
        return self._redis is not None


# 全局单例
cache_client = CacheClient()
