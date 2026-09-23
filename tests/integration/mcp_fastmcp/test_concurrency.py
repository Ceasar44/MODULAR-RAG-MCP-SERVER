import asyncio
import threading
from unittest.mock import Mock

import pytest
from fastmcp import Client

from src.core.response.response_builder import MCPToolResponse
from src.mcp_server.tools.query_knowledge_hub import QueryKnowledgeHubTool

pytestmark = pytest.mark.asyncio


def install_runtime(monkeypatch, entered=None, release=None):
    events = []

    def initialize(self, collection):
        self._current_collection = collection
        events.append(("init", collection))

    def search(self, query, top_k, trace):
        collection = self._current_collection
        events.append(("search", collection))
        if entered and collection == "finance":
            entered.set()
            assert release.wait(5)
        assert self._current_collection == collection == query
        return [Mock(chunk_id=collection, score=1.0, text=collection, metadata={})]

    def rerank(self, query, results, top_k, trace):
        assert self._current_collection == query
        events.append(("rerank", query))
        return results

    def build(self, results, query, collection):
        assert results[0].text == collection
        events.append(("build", collection))
        return MCPToolResponse(content=collection, citations=[], metadata={}, is_empty=False)

    monkeypatch.setattr(QueryKnowledgeHubTool, "_ensure_initialized", initialize)
    monkeypatch.setattr(QueryKnowledgeHubTool, "_perform_search", search)
    monkeypatch.setattr(QueryKnowledgeHubTool, "_apply_rerank", rerank)
    monkeypatch.setattr("src.core.response.response_builder.ResponseBuilder.build", build)
    monkeypatch.setattr("src.mcp_server.tools.query_knowledge_hub.TraceCollector", Mock())
    return events


async def test_http_collections_do_not_share_runtime(http_server, monkeypatch):
    events = install_runtime(monkeypatch)
    async with http_server() as url:
        async with Client(url) as first, Client(url) as second:
            results = await asyncio.gather(
                first.call_tool("query_knowledge_hub", {"query": "finance", "collection": "finance"}),
                second.call_tool("query_knowledge_hub", {"query": "product", "collection": "product"}),
            )
            assert [r.content[0].text for r in results] == ["finance", "product"]
    order = [events[0][1], events[4][1]]
    assert events == [(stage, collection) for collection in order for stage in ("init", "search", "rerank", "build")]


async def test_cancellation_drains_worker_before_releasing_lock(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    events = install_runtime(monkeypatch, entered, release)
    tool = QueryKnowledgeHubTool()
    first = asyncio.create_task(tool.execute("finance", collection="finance"))
    second = None
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        first.cancel()
        second = asyncio.create_task(tool.execute("product", collection="product"))
        await asyncio.sleep(0.05)
        first.cancel()  # Repeated cancellation must not bypass the guard.
        await asyncio.sleep(0.05)
        assert events == [("init", "finance"), ("search", "finance")]
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await first
        if second:
            assert (await second).content == "product"
    assert events == [(stage, collection) for collection in ("finance", "product")
                      for stage in ("init", "search", "rerank", "build")]
