"""FastMCP composition root and ASGI entry point."""

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth import build_auth_provider
from .config import FastMCPServerSettings, get_fastmcp_settings
from .lifespan import rag_lifespan
from .registry import register_tools


def create_fastmcp_server(settings: FastMCPServerSettings | None = None) -> FastMCP:
    settings = settings or get_fastmcp_settings()
    server = FastMCP(
        name="modular-rag-mcp-server",
        version="0.1.0",
        auth=build_auth_provider(settings),
        lifespan=rag_lifespan,
        mask_error_details=True,
        strict_input_validation=True,
        on_duplicate="error",
    )
    register_tools(server)

    @server.custom_route("/health", methods=["GET"])
    async def health(request: Request) -> JSONResponse:
        # Liveness only: providers are initialized lazily by the business tools.
        return JSONResponse({"status": "ok"})

    return server


mcp = create_fastmcp_server()
app = mcp.http_app(path=get_fastmcp_settings().path)
