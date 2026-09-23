"""Use the actual adjacent agent client; set AGENT_ADAPTER_SERVICE_ROOT elsewhere.

Only RAG business tool results are mocked. Client policy, HTTP, authentication,
discovery, serialization and error handling are real.
"""

import importlib
import os
from pathlib import Path

import pytest

from tests.fastmcp_support import http_server, tool_mocks  # noqa: F401

# Imported pytest fixtures are intentionally injected by name.
# ruff: noqa: F811

pytestmark = pytest.mark.asyncio


@pytest.fixture
def agent_module(monkeypatch):
    root = Path(os.environ.get(
        "AGENT_ADAPTER_SERVICE_ROOT",
        str(Path(__file__).resolve().parents[3] / "agent_adapter_service"),
    ))
    if not (root / "src/agent_adapter_service/mcp/clients/rag.py").is_file():
        pytest.skip("Set AGENT_ADAPTER_SERVICE_ROOT to run the cross-repository contract tests")
    monkeypatch.syspath_prepend(str(root / "src"))
    return importlib.import_module("agent_adapter_service.mcp.clients.rag")


async def test_agent_discovery_calls_and_allowlist(http_server, tool_mocks, agent_module):
    async with http_server(token="correct") as url:
        client = agent_module.RagMcpClient(agent_module.RagMcpConfig(url=url), token="correct")
        async with client:
            assert {t.name for t in await client.list_tools()} == {
                "query_knowledge_hub", "list_collections", "get_document_summary",
            }
            assert await client.healthcheck()
            result = await client.call_tool("list_collections", {"include_stats": True})
            assert not result.is_error and result.content[0].text == "test collection"
            result = await client.call_tool("query_knowledge_hub", {
                "query": "test question", "top_k": 3, "collection": "test",
            })
            assert not result.is_error and result.content[0].text == "Test knowledge [1]"
            with pytest.raises(agent_module.AuthorizationError):
                await client.call_tool("delete_database", {})


async def test_agent_invalid_token(http_server, agent_module):
    async with http_server(token="correct") as url:
        client = agent_module.RagMcpClient(agent_module.RagMcpConfig(url=url), token="wrong")
        with pytest.raises(agent_module.IntegrationError):
            await client.connect()


async def test_agent_queries_real_local_index(http_server, agent_module, monkeypatch, tmp_path):
    """Exercise real Chroma, BM25, fusion and response building without paid APIs."""
    from dataclasses import replace
    from unittest.mock import Mock

    from src.core.settings import load_settings
    from src.ingestion.storage.bm25_indexer import BM25Indexer
    from src.libs.embedding.base_embedding import BaseEmbedding
    from src.libs.embedding.embedding_factory import EmbeddingFactory
    from src.libs.vector_store.chroma_store import ChromaStore

    class LocalEmbedding(BaseEmbedding):
        def embed(self, texts, trace=None, **kwargs):
            return [[1.0, 0.0, 0.0] for text in texts]

    original = load_settings()
    settings = replace(
        original,
        vector_store=replace(original.vector_store, provider="chroma",
                             persist_directory=str(tmp_path / "chroma"), collection_name="test"),
        rerank=replace(original.rerank, enabled=False),
    )
    store = ChromaStore(settings)
    store.upsert([{"id": "test_chunk", "vector": [1.0, 0.0, 0.0], "metadata": {
        "text": "FastMCP connects the agent to the knowledge service.",
        "source_ref": "test_doc", "title": "Integration guide", "source_path": "guide.txt",
    }}])
    BM25Indexer(str(tmp_path / "bm25" / "test")).build([
        {"chunk_id": "test_chunk", "term_frequencies": {"fastmcp": 1, "agent": 1}, "doc_length": 2},
    ], collection="test")
    monkeypatch.setattr("src.mcp_server.fastmcp_adapter.lifespan.load_settings", lambda: settings)
    monkeypatch.setattr(EmbeddingFactory, "create", lambda *args, **kwargs: LocalEmbedding())
    monkeypatch.setattr("src.mcp_server.tools.query_knowledge_hub.resolve_path",
                        lambda path: tmp_path / "bm25" / Path(path).name)
    monkeypatch.setattr("src.mcp_server.tools.query_knowledge_hub.TraceCollector", Mock())
    async with http_server() as url:
        async with agent_module.RagMcpClient(agent_module.RagMcpConfig(url=url)) as client:
            result = await client.call_tool("query_knowledge_hub", {
                "query": "fastmcp agent", "collection": "test", "top_k": 3,
            })
            assert not result.is_error
            text = "\n".join(block.text for block in result.content if block.type == "text")
            assert "FastMCP connects the agent" in text
            assert "guide.txt" in text
            collections = await client.call_tool("list_collections", {})
            assert "test" in collections.content[0].text
            summary = await client.call_tool("get_document_summary", {"doc_id": "test_doc", "collection": "test"})
            assert "Integration guide" in summary.content[0].text
