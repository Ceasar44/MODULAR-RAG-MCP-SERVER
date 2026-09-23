"""Expose the existing knowledge retrieval tool."""

from typing import Annotated

from fastmcp import Context
from fastmcp.exceptions import ToolError
from fastmcp.tools import ToolResult
from pydantic import Field

from ..result_adapter import adapt_mcp_tool_response


async def query_knowledge_hub(
    query: Annotated[str, Field(min_length=1)],
    ctx: Context,
    top_k: Annotated[int, Field(ge=1, le=20)] = 5,
    collection: str | None = None,
) -> ToolResult:
    """Search the knowledge base with hybrid retrieval and source citations."""
    if not query.strip():
        raise ToolError("Query cannot be empty")
    response = await ctx.lifespan_context["rag"].query_tool.execute(
        query=query, top_k=top_k, collection=collection,
    )
    return adapt_mcp_tool_response(response)
