# FastMCP HTTP 服务

HTTP 入口复用已有三个 RAG 工具，默认监听 `http://localhost:8002/mcp`。
原 stdio 入口 `python -m src.mcp_server.server` 继续可用。

## Docker 部署（Linux 服务器）

仓库根目录提供 `Dockerfile`、`compose.yaml`、`.env.production.example` 和
`config/settings.production.yaml`。默认使用单容器、单进程，MCP 路径固定为 `/mcp`，
宿主机仅监听 `127.0.0.1:8002`，通过 HTTPS 网关对外提供服务。

### 准备配置与数据

```sh
cp .env.production.example .env.production
chmod 600 .env.production
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
mkdir -p data logs
sudo chown -R 10001:10001 data logs
```

将生成的令牌写入 `.env.production` 的 `RAG_MCP_TOKEN`，填写 `OPENAI_API_KEY`。
使用 MinerU 入库时还需填写 `MINERU_API_KEY`。不要提交填好凭据的文件。
Compose 强制开启认证，并在 Token 或模型密钥为空时拒绝启动。
环境变量由 Compose 显式传入容器，应用本身不读取 `.env` 文件。
可参考 [Docker Compose 环境变量说明](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/)。

生产 YAML 保留了现有模型配置，但清除了 API Key；部署前核对模型、服务地址和
embedding 实际维度是否与已有知识库一致。三个 OpenAI-compatible provider 共用
`OPENAI_API_KEY`。YAML 的 `api_key` 必须保持 `null`，否则其优先级高于环境变量。
配置加载器不支持 `${VAR}` 字符串插值。

迁移知识库时暂停入库，完整复制 `data/`，包含 Chroma、BM25、图片索引、图片文件和
入库记录，然后重新检查目标目录权限。不要只复制 Chroma，也不要在写入期间直接拷贝数据库。
检查迁移数据中的 Windows 绝对路径；需要时重新入库。更换 embedding 模型需要重建索引。
新部署没有数据时，需先通过入库脚本建立知识库。

容器以 UID/GID `10001:10001` 运行。配置文件只读挂载，`data/` 和 `logs/` 可写挂载；
挂载源必须已存在，避免 Docker 自动创建错误的目录或权限。
镜像只复制源码和构建元数据，本地配置、凭据、数据、日志均不进入构建上下文。
当前仍使用项目声明的依赖范围（FastMCP 固定为 4.0.3）；其他依赖尚未形成经过 Linux
验证的完整锁文件。首次验证成功后应保存并复用该镜像，避免每次发布重新解析依赖。

### 启动与检查

```sh
docker compose --env-file .env.production config --quiet
docker compose --env-file .env.production up -d --build
docker compose --env-file .env.production ps
docker compose --env-file .env.production logs --tail=100 rag-system
curl -f http://127.0.0.1:8002/health
```

`/health` 无需 Token，仅返回 `{"status":"ok"}`，表示进程可以响应 HTTP，
不代表延迟初始化的数据库或模型 API 可用。上线还必须执行一次真实检索。
Docker 的 unhealthy 状态用于监控；`restart: unless-stopped` 仅在进程退出等情况下重启，
不会因 unhealthy 自动重启。Docker 日志有大小轮转，`logs/traces.jsonl` 需另设归档策略。

### HTTPS 网关与客户端

`deploy/nginx.conf.example` 是宿主机 Nginx 的配置示例。替换域名、证书路径，
使用已有证书配置 HTTPS，再执行 `nginx -t` 并重载 Nginx。它保留认证和 MCP 协议头，
关闭响应缓冲，将 `/mcp` 原样转发到本机 8002 端口。

外部客户端使用 `https://rag.example.com/mcp`，发送
`Authorization: Bearer <RAG_MCP_TOKEN>`。这是 MCP Streamable HTTP 端点，
应使用 MCP 客户端完成协议调用，而非普通 REST JSON 请求。
内部 Agent 若加入同一个 Docker 网络，可使用 `http://rag-system:8002/mcp`。
若 Nginx 也在容器中，应加入该网络并把 upstream 改为 `http://rag-system:8002`。

客户端验收示例（在安装 FastMCP 的环境中执行，并事先导出这两个环境变量）：

```python
import asyncio
import os
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

async def main():
    transport = StreamableHttpTransport(
        os.environ["RAG_MCP_URL"],
        headers={"Authorization": f"Bearer {os.environ['RAG_MCP_TOKEN']}"},
    )
    async with Client(transport) as client:
        print([tool.name for tool in await client.list_tools()])
        print(await client.call_tool("list_collections", {}))
        print(await client.call_tool("query_knowledge_hub", {
            "query": "替换成已有知识库可以回答的问题", "top_k": 3,
        }))

asyncio.run(main())
```

验收时还需检查错误 Token 被拒绝、文档摘要/图片可返回，以及重建容器后数据仍可检索。

### 文档入库与更新

MCP 只公开三个读取工具。把源文档放入 `data/documents/` 后，使用单独的一次性任务入库。
为避免当前本地索引的并发写入和查询缓存问题，暂停服务，入库后重新启动：

```sh
docker compose --env-file .env.production stop rag-system
docker compose --env-file .env.production run --rm --no-deps rag-system \
  python scripts/ingest.py --path /app/data/documents --collection knowledge_hub
docker compose --env-file .env.production up -d rag-system
```

升级前备份 `data/`，保留上一版镜像；数据库格式发生变化时，回滚必须同时恢复匹配的数据备份。
当前查询锁保护 collection 切换，因此查询串行执行。不要直接增加 workers 或共享本地数据卷
运行多个副本。扩展前需处理查询实例隔离、存储服务化及 MCP 会话策略；
参考 [FastMCP HTTP 部署说明](https://github.com/PrefectHQ/fastmcp/blob/main/docs/deployment/http.mdx)。

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
