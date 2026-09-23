"""Per-server RAG tool ownership and startup preloading."""

import asyncio
import importlib
import logging
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass

from src.core.settings import Settings, load_settings
from src.mcp_server.tools.get_document_summary import GetDocumentSummaryTool
from src.mcp_server.tools.list_collections import ListCollectionsTool
from src.mcp_server.tools.query_knowledge_hub import QueryKnowledgeHubTool

logger = logging.getLogger(__name__)


@dataclass
class FastMCPAppContext:
    settings: Settings
    query_tool: QueryKnowledgeHubTool
    # These tools have cheap constructors. Use request-local instances to avoid
    # concurrent lazy initialization of their Chroma clients/configuration.

    def collection_tool(self) -> ListCollectionsTool:
        return ListCollectionsTool(settings=self.settings)

    def document_tool(self) -> GetDocumentSummaryTool:
        return GetDocumentSummaryTool(settings=self.settings)


def _preload_heavy_imports() -> None:
    for name in (
        "chromadb",
        "src.core.query_engine.query_processor",
        "src.core.query_engine.hybrid_search",
        "src.core.query_engine.dense_retriever",
        "src.core.query_engine.sparse_retriever",
        "src.core.query_engine.reranker",
        "src.ingestion.storage.bm25_indexer",
        "src.libs.embedding.embedding_factory",
        "src.libs.vector_store.vector_store_factory",
    ):
        try:
            importlib.import_module(name)
        except ImportError:
            logger.warning("Optional preload unavailable: %s", name)


@asynccontextmanager
async def rag_lifespan(server):
    settings = await asyncio.to_thread(load_settings)
    await asyncio.to_thread(_preload_heavy_imports)
    # ExitStack provides an ownership boundary for future managed clients.
    # Current legacy tools expose no close API and create no clients here.
    async with AsyncExitStack() as resources:
        context = FastMCPAppContext(settings, QueryKnowledgeHubTool(settings=settings))
        logger.info("RAG HTTP runtime started")
        try:
            yield {"rag": context, "resources": resources}
        finally:
            # FastMCP drains active requests before exiting this lifespan.
            # No process-global tool singleton survives a server restart.
            logger.info("RAG HTTP runtime stopped")
