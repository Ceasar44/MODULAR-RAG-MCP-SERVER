"""Expose existing collection discovery."""

from fastmcp import Context
from fastmcp.tools import ToolResult

from ..result_adapter import adapt_call_tool_result


async def list_collections(ctx: Context, include_stats: bool = True) -> ToolResult:
    """List available document collections, optionally including statistics."""
    result = await ctx.lifespan_context["rag"].collection_tool().execute(
        include_stats=include_stats,
    )
    return adapt_call_tool_result(result)
