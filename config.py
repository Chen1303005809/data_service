"""应用配置，从环境变量读取。"""

import os
from dataclasses import dataclass, field


@dataclass
class Config:
    """统一配置对象。"""

    external_api_url: str = field(
        default_factory=lambda: os.getenv("EXTERNAL_API_URL", "")
    )
    redis_url: str = field(
        default_factory=lambda: os.getenv("REDIS_URL", "redis://localhost:6379/0")
    )
    cache_ttl_seconds: int = field(
        default_factory=lambda: int(os.getenv("CACHE_TTL_SECONDS", "300"))
    )
    refresh_interval_seconds: int = field(
        default_factory=lambda: int(os.getenv("REFRESH_INTERVAL_SECONDS", "60"))
    )
    max_limit: int = field(
        default_factory=lambda: int(os.getenv("MAX_LIMIT", "500"))
    )
    default_limit: int = field(
        default_factory=lambda: int(os.getenv("DEFAULT_LIMIT", "50"))
    )
    log_level: str = field(
        default_factory=lambda: os.getenv("LOG_LEVEL", "INFO")
    )

    def validate(self) -> None:
        """校验必填配置项。"""
        if not self.external_api_url:
            raise ValueError("EXTERNAL_API_URL is required but not set")
        if self.cache_ttl_seconds <= 0:
            raise ValueError("CACHE_TTL_SECONDS must be positive")
        if self.refresh_interval_seconds <= 0:
            raise ValueError("REFRESH_INTERVAL_SECONDS must be positive")
        if self.max_limit <= 0:
            raise ValueError("MAX_LIMIT must be positive")
        if self.default_limit <= 0 or self.default_limit > self.max_limit:
            raise ValueError("DEFAULT_LIMIT must be between 1 and MAX_LIMIT")


# 全局单例
config = Config()
