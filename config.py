"""应用配置，从环境变量读取。"""

import os
from dataclasses import dataclass, field


def _parse_int_list(value: str) -> set[int]:
    """解析逗号分隔的整数字符串为集合，如 '1,6' → {1, 6}。"""
    if not value.strip():
        return set()
    return {int(x.strip()) for x in value.split(",") if x.strip()}


@dataclass
class Config:
    """统一配置对象。"""

    # 外部数据源
    ins_api_url: str = field(
        default_factory=lambda: os.getenv("INS_API_URL", "")
    )
    price_api_url: str = field(
        default_factory=lambda: os.getenv("PRICE_API_URL", "")
    )
    # Redis
    redis_url: str = field(
        default_factory=lambda: os.getenv("REDIS_URL", "redis://localhost:6379/0")
    )
    # 缓存与刷新
    cache_ttl_seconds: int = field(
        default_factory=lambda: int(os.getenv("CACHE_TTL_SECONDS", "300"))
    )
    refresh_interval_seconds: int = field(
        default_factory=lambda: int(os.getenv("REFRESH_INTERVAL_SECONDS", "60"))
    )
    # 分页
    max_limit: int = field(
        default_factory=lambda: int(os.getenv("MAX_LIMIT", "500"))
    )
    default_limit: int = field(
        default_factory=lambda: int(os.getenv("DEFAULT_LIMIT", "50"))
    )
    # 产品类型映射（/ins 中 pi.pt 字段的值，以样例注释为准：1=期货, 2=期权, 6=个股期权）
    option_types: set[int] = field(
        default_factory=lambda: _parse_int_list(os.getenv("OPTION_TYPES", "2"))
    )
    future_types: set[int] = field(
        default_factory=lambda: _parse_int_list(os.getenv("FUTURE_TYPES", "1"))
    )
    # 日志
    log_level: str = field(
        default_factory=lambda: os.getenv("LOG_LEVEL", "INFO")
    )

    def validate(self) -> None:
        """校验必填配置项。"""
        if not self.ins_api_url:
            raise ValueError("INS_API_URL is required but not set")
        if not self.price_api_url:
            raise ValueError("PRICE_API_URL is required but not set")
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
