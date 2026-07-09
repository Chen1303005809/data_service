"""Redis 客户端封装：DataFrame 的存储与读取。

支持分离的缓存键：合约（contracts:latest）和现货（spot:latest）。
"""

from __future__ import annotations
from io import BytesIO

import logging
from datetime import datetime

import pandas as pd
import redis.asyncio as aioredis

from config import CST, config

logger = logging.getLogger(__name__)

CACHE_KEY_CONTRACTS = "contracts:latest"
CACHE_KEY_SPOT = "spot:latest"
TEMP_KEY_PREFIX = "cache:temp:"


class CacheClient:
    """Redis 缓存客户端，管理 DataFrame 的序列化存储。

    支持两个分离的缓存：
    - contracts:latest — 期货/期权数据
    - spot:latest — 现货数据

    同时维护进程内 local_cache 用于 Redis 不可用时的降级。
    """

    def __init__(self) -> None:
        self._redis: aioredis.Redis | None = None
        # 按 key 分别缓存，{key_name: (df, cached_at)}
        self._local: dict[str, tuple[pd.DataFrame, datetime]] = {}

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

    async def get_df(self, key: str = CACHE_KEY_CONTRACTS) -> pd.DataFrame | None:
        """获取指定 key 的缓存 DataFrame（优先 Redis，回退本地）。"""
        if self._redis:
            try:
                data = await self._redis.get(key)
                if data:
                    return pd.read_parquet(BytesIO(data))
            except Exception:
                logger.exception("Failed to read from Redis, falling back to local")

        if key in self._local:
            return self._local[key][0].copy()
        return None

    async def get_cached_at(self, key: str = CACHE_KEY_CONTRACTS) -> datetime | None:
        """获取指定 key 的缓存时间戳。"""
        if self._redis:
            try:
                ttl = await self._redis.ttl(key)
                if ttl > 0:
                    return datetime.now(CST).replace(microsecond=0)
            except Exception:
                pass

        if key in self._local:
            return self._local[key][1]
        return None

    async def is_stale(self, key: str = CACHE_KEY_CONTRACTS) -> bool | None:
        """判断指定 key 的缓存是否过期。None 表示无法判断。"""
        if self._redis:
            try:
                ttl = await self._redis.ttl(key)
                if ttl == -2:  # key 不存在
                    return None
                return ttl <= 0
            except Exception:
                pass
        return None

    # ---- 写入 ----

    async def set_df(self, df: pd.DataFrame, key_override: str | None = None) -> None:
        """写入 DataFrame 到 Redis + 本地缓存。

        使用临时 key + RENAME 保证原子替换。
        本地缓存始终更新，Redis 不可用时降级。

        Args:
            df: 要缓存的 DataFrame
            key_override: 缓存 key，默认 contracts:latest
        """
        key = key_override or CACHE_KEY_CONTRACTS
        now = datetime.now(CST)

        # 更新本地缓存
        self._local[key] = (df.copy(), now)

        if self._redis:
            buf = BytesIO()
            df.to_parquet(buf, index=False)

            try:
                temp_key = f"{TEMP_KEY_PREFIX}{int(now.timestamp())}"
                await self._redis.set(temp_key, buf.getvalue(), ex=config.cache_ttl_seconds)
                await self._redis.rename(temp_key, key)
                logger.info("Cache refreshed: key=%s %d rows, TTL=%ds", key, len(df), config.cache_ttl_seconds)
            except Exception:
                logger.exception("Failed to write cache to Redis (local cache updated)")
        else:
            logger.info("Local cache updated: key=%s %d rows (Redis unavailable)", key, len(df))

    @property
    def redis_available(self) -> bool:
        """Redis 是否当前可用。"""
        return self._redis is not None


# 全局单例
cache_client = CacheClient()
