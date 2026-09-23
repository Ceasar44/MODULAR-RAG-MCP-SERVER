# FastMCP HTTP 服务

HTTP 入口复用已有三个 RAG 工具，默认监听 `http://localhost:8002/mcp`。
原 stdio 入口 `python -m src.mcp_server.server` 继续可用。

## 安装与启动

在项目根目录、已激活的 Python 环境中运行：

```sh
python -m pip install -e ".[dev]"
python -m src.mcp_server.fastmcp_adapter.server
```

安装后也可执行 `rag-mcp-http`。ASGI 部署方式：

```sh
uvicorn src.mcp_server.fastmcp_adapter.app:app --host 0.0.0.0 --port 8002
```

ASGI 模式的监听地址和端口由 uvicorn 参数控制；MCP 路径仍使用 `RAG_MCP_PATH`。
RAG 模型、数据库、重排配置继续从 `config/settings.yaml` 加载。
启动会预加载查询依赖，模型和数据库客户端仍按业务工具原有方式延迟初始化。

## 环境变量

`.env.example` 是配置示例，需要将变量导出到进程环境；服务不自动加载 `.env`。

| 变量 | 默认值 | 作用 |
| --- | --- | --- |
| `RAG_MCP_HOST` | `0.0.0.0` | CLI 监听地址 |
| `RAG_MCP_PORT` | `8002` | CLI 监听端口 |
| `RAG_MCP_PATH` | `/mcp` | HTTP MCP 路径 |
| `RAG_MCP_AUTH_ENABLED` | `false` | 是否校验 Bearer Token |
| `RAG_MCP_TOKEN` | 空 | 启用认证时必填 |
| `RAG_MCP_LOG_LEVEL` | `INFO` | CLI 日志级别 |

PowerShell 认证启动示例：

```powershell
$env:RAG_MCP_AUTH_ENABLED = "true"
$env:RAG_MCP_TOKEN = "replace-with-your-service-token"
python -m src.mcp_server.fastmcp_adapter.server
```

## Agent 连接

已核对 `agent_adapter_service/configs/mcp/rag.yaml` 和 `.env.example`，无需修改客户端。
Agent 配置 `RAG_MCP_URL=http://localhost:8002/mcp`，认证开启时两端使用相同的
`RAG_MCP_TOKEN`。不同容器中将 Agent 的 URL 设置为 `http://rag-system:8002/mcp`。

仅暴露以下工具，`Context` 等内部参数不会出现在工具 Schema 中：

| 工具 | 参数 |
| --- | --- |
| `query_knowledge_hub` | `query` 非空；`top_k` 为 1–20，默认 5；`collection` 可选 |
| `list_collections` | `include_stats` 默认 true |
| `get_document_summary` | `doc_id` 非空；`collection` 可选 |

成功结果保留文本、图片、资源块和已有结构化内容；无检索结果仍属于成功。
业务错误转换成 MCP 工具错误，内部异常详情不发给客户端。

## 版本兼容与并发

固定使用 `fastmcp==4.0.3`，它依赖 MCP SDK 2.x。SDK 2.x 的 Python 字段改为
`is_error`、`input_schema`、`mime_type` 等；JSON 协议中的字段名仍由 SDK 处理。
stdio 注册层兼容 SDK 1.x 装饰器接口和 SDK 2.x 回调接口，原 stdio 启动命令不变。
参考 [官方 SDK 迁移说明](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/whats-new.md)。

每个 HTTP 服务生命周期持有独立查询工具实例。查询锁覆盖初始化、检索、重排和响应构建。
客户端取消请求时，后台线程中的查询先完成再释放锁，避免切换 collection 造成串数据。
因此单进程查询按顺序执行；取消可能需要等待正在执行的模型或数据库调用结束。
生命周期结束后该服务的工具实例不再复用。现有业务工具未提供显式资源关闭接口，
适配层通过生命周期资源栈为后续可关闭客户端保留统一管理位置。

## 测试

```sh
python -m pytest tests/unit/mcp_fastmcp tests/integration/mcp_fastmcp tests/e2e/test_agent_adapter_mcp.py
python -m pytest tests/unit/test_protocol_handler.py tests/integration/test_mcp_server.py
```

HTTP 测试启动真实本地端口，覆盖现代发现与旧版 initialize 握手、认证、工具参数、错误、
多 collection 隔离和取消。跨仓库测试默认查找相邻的 `agent_adapter_service`，也可设置
`AGENT_ADAPTER_SERVICE_ROOT` 为该仓库根目录；缺少仓库时这些测试明确跳过。
使用真实 `RagMcpClient`，不替换客户端实现。真实检索测试使用临时 Chroma/BM25 数据，
只替换外部 embedding 为确定性本地实现并关闭重排模型，不调用付费 API、不改现有知识库。
