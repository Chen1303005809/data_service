"""现货价格解析器 — 薄重导出层，保持 syncer/sync.py 向后兼容。

所有核心逻辑已迁移到 spot/client.py，本模块仅作 re-export。
"""

from __future__ import annotations

from spot.client import (  # noqa: F401 — 重导出给 syncer/sync.py 使用
    HAS_AKSHARE,
    fetch_spot_history,
    fetch_spot_records,
)
