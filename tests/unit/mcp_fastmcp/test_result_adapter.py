import pytest
from fastmcp.exceptions import ToolError
from mcp import types

from src.core.response.response_builder import MCPToolResponse
from src.mcp_server.fastmcp_adapter.result_adapter import (
    adapt_call_tool_result,
    adapt_mcp_tool_response,
)


def test_preserves_multimodal_and_structured_content():
    blocks = [
        types.TextContent(type="text", text="citation"),
        types.ImageContent(type="image", data="aGVsbG8=", mimeType="image/png"),
        types.EmbeddedResource(type="resource", resource=types.TextResourceContents(
            uri="file:///document.txt", text="document",
        )),
    ]
    result = adapt_call_tool_result(types.CallToolResult(
        content=blocks, structuredContent={"title": "Document"},
    ))
    assert result.content == blocks
    assert result.structured_content == {"title": "Document"}


@pytest.mark.parametrize("text", ["Traceback: secret=abc", "Error: api_key=abc", ""])
def test_errors_do_not_leak_provider_details(text):
    with pytest.raises(ToolError, match="^RAG tool execution failed$"):
        adapt_call_tool_result(types.CallToolResult(
            content=[types.TextContent(type="text", text=text)], isError=True,
        ))


def test_empty_search_is_success():
    response = MCPToolResponse(content="No results", citations=[], metadata={}, is_empty=True)
    assert adapt_mcp_tool_response(response).content[0].text == "No results"


def test_query_error_is_failure():
    response = MCPToolResponse(content="private", citations=[], metadata={"error": "private"}, is_empty=True)
    with pytest.raises(ToolError, match="RAG tool execution failed"):
        adapt_mcp_tool_response(response)
