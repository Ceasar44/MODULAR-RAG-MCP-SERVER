"""Preserve MCP content blocks and distinguish empty retrieval from failure."""

from typing import TYPE_CHECKING

from fastmcp.exceptions import ToolError
from fastmcp.tools import ToolResult
from mcp import types

if TYPE_CHECKING:
    from src.core.response.response_builder import MCPToolResponse

_ERROR = "RAG tool execution failed"


def _extract_error_text(content_blocks: list) -> str:
    # Legacy tools interpolate arbitrary provider errors (including URLs, paths
    # and potentially credentials). Only forward known public messages.
    safe_messages = {"Query cannot be empty", "Document ID cannot be empty"}
    for block in content_blocks:
        if isinstance(block, types.TextContent) and block.text in safe_messages:
            return block.text
    return _ERROR


def adapt_call_tool_result(result: types.CallToolResult) -> ToolResult:
    if result.is_error:
        raise ToolError(_extract_error_text(result.content))
    return ToolResult(content=result.content, structured_content=result.structured_content)


def adapt_mcp_tool_response(response: "MCPToolResponse") -> ToolResult:
    if "error" in response.metadata:
        raise ToolError(_ERROR)
    return ToolResult(content=response.to_mcp_content())
