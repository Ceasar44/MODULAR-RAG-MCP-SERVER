"""Bearer token authentication for service-to-service MCP calls."""

from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

from .config import FastMCPServerSettings


def build_auth_provider(settings: FastMCPServerSettings) -> StaticTokenVerifier | None:
    if not settings.auth_enabled:
        return None
    return StaticTokenVerifier(tokens={
        settings.auth_token: {"client_id": "rag-agent", "scopes": []},
    })
