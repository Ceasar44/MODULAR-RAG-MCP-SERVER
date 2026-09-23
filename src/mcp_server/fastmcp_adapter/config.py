"""HTTP transport settings, independent of RAG provider configuration."""

import os
from dataclasses import dataclass, field
from functools import lru_cache


@dataclass(frozen=True)
class FastMCPServerSettings:
    host: str = "0.0.0.0"
    port: int = 8002
    path: str = "/mcp"
    auth_enabled: bool = False
    auth_token: str | None = field(default=None, repr=False)
    log_level: str = "INFO"

    def __post_init__(self) -> None:
        if not self.host.strip():
            raise ValueError("RAG_MCP_HOST must not be empty")
        if isinstance(self.port, bool) or not isinstance(self.port, int) or not 1 <= self.port <= 65535:
            raise ValueError("RAG_MCP_PORT must be between 1 and 65535")
        if (not self.path.startswith("/") or self.path.startswith("//")
                or any(c.isspace() or c in "?#{}" for c in self.path)):
            raise ValueError("RAG_MCP_PATH must be an absolute HTTP path")
        if self.auth_enabled and not (self.auth_token and self.auth_token.strip()):
            raise ValueError("RAG_MCP_TOKEN is required when authentication is enabled")
        if self.log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("Invalid RAG_MCP_LOG_LEVEL")


def load_fastmcp_settings() -> FastMCPServerSettings:
    value = os.getenv("RAG_MCP_AUTH_ENABLED", "false").strip().lower()
    if value not in {"true", "false", "1", "0", "yes", "no", "on", "off"}:
        raise ValueError("Invalid RAG_MCP_AUTH_ENABLED boolean")
    try:
        port = int(os.getenv("RAG_MCP_PORT", "8002"))
    except ValueError:
        raise ValueError("RAG_MCP_PORT must be an integer") from None
    return FastMCPServerSettings(
        host=os.getenv("RAG_MCP_HOST", "0.0.0.0").strip(),
        port=port,
        path=os.getenv("RAG_MCP_PATH", "/mcp"),
        auth_enabled=value in {"true", "1", "yes", "on"},
        auth_token=os.getenv("RAG_MCP_TOKEN") or None,
        log_level=os.getenv("RAG_MCP_LOG_LEVEL", "INFO").strip().upper(),
    )


@lru_cache(maxsize=1)
def get_fastmcp_settings() -> FastMCPServerSettings:
    return load_fastmcp_settings()
