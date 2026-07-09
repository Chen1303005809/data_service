"""合约数据服务入口：FastAPI 应用 + 定时同步调度。

两个独立的调度任务：
1. 合约（期货/期权）：从 /ins + /price API 拉取，默认每 10 秒
2. 现货（akshare）：从 akshare 拉取，默认每 4 小时
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from fastapi import FastAPI

# ⚠️ load_dotenv() 必须在 config / cache_client 等模块 import 之前调用，
# 因为这些模块在 import 时就会读取环境变量（如 INS_API_URL）。
load_dotenv()

from api.router import router       # noqa: E402
from api.spot_router import spot_router  # noqa: E402
from cache.redis_client import cache_client  # noqa: E402
from config import CST, config      # noqa: E402
from syncer.sync import fetch_contracts_and_sync, fetch_spot_and_sync  # noqa: E402


class CSTFormatter(logging.Formatter):
    """使用 CST (Asia/Shanghai) 时区的日志格式化器。"""

    def formatTime(self, record, datefmt=None):
        ct = datetime.fromtimestamp(record.created, CST)
        if datefmt:
            return ct.strftime(datefmt)
        return ct.strftime("%Y-%m-%d %H:%M:%S")


_log_format = "%(asctime)s %(levelname)s [%(name)s] %(message)s"

logging.basicConfig(
    level=getattr(logging, config.log_level.upper(), logging.INFO),
    format=_log_format,
)
# 替换所有 handler 的 formatter 为 CST 时区版本
for _h in logging.getLogger().handlers:
    _h.setFormatter(CSTFormatter(_log_format))

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone=CST)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理。"""
    # ---- 启动 ----
    logger.info("Starting data_service...")
    config.validate()
    await cache_client.connect()

    # 冷启动：分别同步合约和现货
    logger.info("Cold-start: syncing contracts...")
    cnt = await fetch_contracts_and_sync()
    if cnt < 0 and await cache_client.get_df("contracts:latest") is None:
        logger.warning("Cold-start: contracts sync failed")

    logger.info("Cold-start: syncing spot...")
    spt = await fetch_spot_and_sync()
    if spt < 0 and await cache_client.get_df("spot:latest") is None:
        logger.warning("Cold-start: spot sync failed (akshare data may be unavailable)")

    # 启动定时刷新：合约高频、现货低频
    scheduler.add_job(
        fetch_contracts_and_sync,
        "interval",
        seconds=config.contracts_refresh_interval_seconds,
        id="contracts_sync_job",
        replace_existing=True,
    )
    scheduler.add_job(
        fetch_spot_and_sync,
        "interval",
        seconds=config.spot_refresh_interval_seconds,
        id="spot_sync_job",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(
        "Scheduler started: contracts every %ds, spot every %ds, TTL=%ds",
        config.contracts_refresh_interval_seconds,
        config.spot_refresh_interval_seconds,
        config.cache_ttl_seconds,
    )

    yield  # ---- 运行中 ----

    # ---- 关闭 ----
    logger.info("Shutting down...")
    scheduler.shutdown(wait=False)
    await cache_client.disconnect()
    logger.info("Shutdown complete")


app = FastAPI(
    title="合约数据服务",
    description="为 DIFY 工具节点提供期货/期权/现货数据查询。",
    version="2.0.0",
    lifespan=lifespan,
)
app.include_router(router)
app.include_router(spot_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, log_level=config.log_level.lower())
