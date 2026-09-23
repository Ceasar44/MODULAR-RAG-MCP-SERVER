from unittest.mock import Mock

import pytest

from src.mcp_server.fastmcp_adapter import lifespan


@pytest.mark.asyncio
async def test_runtime_is_per_lifespan_and_resources_close(monkeypatch):
    settings = Mock()
    monkeypatch.setattr(lifespan, "load_settings", lambda: settings)
    monkeypatch.setattr(lifespan, "_preload_heavy_imports", lambda: None)
    cleanup = Mock()
    async with lifespan.rag_lifespan(None) as first:
        first["resources"].callback(cleanup)
        async with lifespan.rag_lifespan(None) as second:
            assert first["rag"].settings is settings
            assert first["rag"].query_tool is not second["rag"].query_tool
            assert first["rag"].document_tool() is not first["rag"].document_tool()
    cleanup.assert_called_once()


def test_preload_missing_optional_modules_is_nonfatal(monkeypatch):
    importer = Mock(side_effect=ImportError("optional dependency absent"))
    monkeypatch.setattr(lifespan.importlib, "import_module", importer)
    lifespan._preload_heavy_imports()
    assert importer.call_count == 9
