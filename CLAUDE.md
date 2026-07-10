# data_service 代码索引

按"问题"定位代码文件。新会话开局先扫这一段,再决定读哪里。

## 一句话定位

FastAPI 行情数据服务:每 10s 拉合约、每 4h 拉现货 → Redis(parquet)→ 缓存优先 + 实时兜底 → `/api/contracts`、`/api/kline` 两个查询接口。

## 按问题找文件

| 问题 | 看哪里 |
|---|---|
| 启动入口、定时调度、生命周期 | `main.py` |
| 环境变量、所有可配项 | `config.py` |
| HTTP 接口定义(`/api/contracts`、`/api/kline`、`/health`) | `api/router.py` |
| 查询主流程(缓存优先 + 兜底 + 过滤 + 排序 + 分页) | `engine/filter.py` |
| 缓存读/写(parquet 序列化,Redis 挂时降级 local_cache) | `cache/redis_client.py` |
| 合约基础信息解析(`/ins` 接口) | `syncer/parser/ins_parser.py` |
| 价格行情解析(`/price` 接口,价格 ÷10000) | `syncer/parser/price_parser.py` |
| 现货/基差拉取(akshare,数据空时回退 7 天) | `syncer/parser/spot_parser.py` |
| 同步编排(拉 + 合并 + 写缓存) | `syncer/sync.py` |
| K线 TCP 客户端(二进制协议 + xor 校验 + 指数退避) | `kline/client.py` |
| K线 Pydantic 模型 | `kline/models.py` |
| 品种代码归一化(`ag`/`AG`/`ag2507` → 规范) | `kline/symbol_normalizer.py` |
| 所有 Pydantic 模型(产品类型、InsInfo、PriceInfo、查询参数/响应) | `models/schemas.py` |
| K线/合约数据 → 中文自然语言描述 | `describe_natural.py` |
| K线字段口径定义(开高低收成交量等) | `k_history_rule.md` |

## 关键调用链(从上到下)

- `main.py` → `api/router.py` 暴露 HTTP
- `api/router.py` → `engine/filter.py::query` 处理合约查询
- `api/router.py` → `kline/client.py::kline_client` 处理 K线查询
- `engine/filter.py` → `cache/redis_client.py` 读缓存;缓存空时 → `syncer/sync.py` 兜底
- `syncer/sync.py` → `syncer/parser/ins_parser.py` + `syncer/parser/price_parser.py` + `syncer/parser/spot_parser.py` 拉数据
- 解析产物 → `models/schemas.py` 的 `InsInfo` / `PriceInfo`
- 同步结果 → `cache/redis_client.py` 写回

## 全局单例与共享对象

- `config.config` — 配置
- `cache.redis_client.cache_client` — 缓存客户端
- `kline.client.kline_client` — K线 TCP 客户端
- `kline.symbol_normalizer._CASE_INSENSITIVE_INDEX` — 品种代码索引
- `syncer.parser.price_parser.get_main_flags / reset_main_flags` — 主力标记状态

## 改动时的注意事项

- 加新接口:在 `api/router.py` 加路由,在 `models/schemas.py` 加模型,在 `config.py` 加可配项(如有)。
- 加新数据源:仿 `syncer/parser/spot_parser.py` 写解析器,接到 `syncer/sync.py`。
- 改 K线协议:`kline/client.py` 里的 `pack_request` / `_StreamParser` 是核心。
- 改缓存格式:注意 `cache/redis_client.py` 用 parquet 序列化 DataFrame,Redis key 在 `CACHE_KEY_CONTRACTS` / `CACHE_KEY_SPOT`。
