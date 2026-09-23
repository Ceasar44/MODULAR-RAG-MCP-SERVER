import pytest

from src.mcp_server.fastmcp_adapter.config import (
    FastMCPServerSettings,
    get_fastmcp_settings,
    load_fastmcp_settings,
)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    import os
    for key in os.environ:
        if key.startswith("RAG_MCP_"):
            monkeypatch.delenv(key)
    get_fastmcp_settings.cache_clear()
    yield
    get_fastmcp_settings.cache_clear()


def test_defaults_and_cache():
    assert load_fastmcp_settings() == FastMCPServerSettings()
    assert get_fastmcp_settings() is get_fastmcp_settings()


def test_custom_settings(monkeypatch):
    for name, value in {
        "HOST": "127.0.0.1", "PORT": "9000", "PATH": "/rag/mcp",
        "AUTH_ENABLED": "true", "TOKEN": "secret", "LOG_LEVEL": "debug",
    }.items():
        monkeypatch.setenv("RAG_MCP_" + name, value)
    settings = load_fastmcp_settings()
    assert settings == FastMCPServerSettings("127.0.0.1", 9000, "/rag/mcp", True, "secret", "DEBUG")
    assert "secret" not in repr(settings)


@pytest.mark.parametrize("name,value", [
    ("PORT", "0"), ("PORT", "65536"), ("PORT", "abc"),
    ("PATH", "mcp"), ("PATH", "//host"), ("PATH", "/mcp?x=1"),
    ("HOST", " "), ("LOG_LEVEL", "oops"), ("AUTH_ENABLED", "maybe"),
    ("AUTH_ENABLED", "true"),
])
def test_invalid_settings(monkeypatch, name, value):
    monkeypatch.setenv("RAG_MCP_" + name, value)
    with pytest.raises(ValueError):
        load_fastmcp_settings()


def test_direct_settings_validate():
    with pytest.raises(ValueError):
        FastMCPServerSettings(auth_enabled=True, auth_token=" ")
