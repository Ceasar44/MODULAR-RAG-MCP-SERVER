"""Expose the existing document summary tool."""

from typing import Annotated

from fastmcp import Context
from fastmcp.exceptions import ToolError
from fastmcp.tools import ToolResult
from pydantic import Field

from ..result_adapter import adapt_call_tool_result


async def get_document_summary(
    doc_id: Annotated[str, Field(min_length=1)],
    ctx: Context,
    collection: str | None = None,
) -> ToolResult:
    """Get a document's title, summary, tags, source and metadata."""
    if not doc_id.strip():
        raise ToolError("Document ID cannot be empty")
    result = await ctx.lifespan_context["rag"].document_tool().execute(
        doc_id=doc_id, collection=collection,
    )
    return adapt_call_tool_result(result)
