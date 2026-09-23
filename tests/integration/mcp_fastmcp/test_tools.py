import pytest
from fastmcp import Client
from mcp import types

pytestmark = pytest.mark.asyncio


async def test_tool_calls_forward_arguments_and_results(http_server, tool_mocks):
    async with http_server() as url, Client(url) as client:
        result = await client.call_tool("query_knowledge_hub", {"query": "test", "top_k": 3, "collection": "test"})
        assert not result.is_error and result.content[0].text == "Test knowledge [1]"
        tool_mocks["query"].assert_awaited_once_with(query="test", top_k=3, collection="test")
        result = await client.call_tool("list_collections", {"include_stats": False})
        assert result.content[0].text == "test collection"
        tool_mocks["collections"].assert_awaited_once_with(include_stats=False)
        result = await client.call_tool("get_document_summary", {"doc_id": "doc", "collection": "test"})
        assert '"summary":"Summary"' in result.content[0].text
        tool_mocks["summary"].assert_awaited_once_with(doc_id="doc", collection="test")


@pytest.mark.parametrize("name,args", [
    ("query_knowledge_hub", {"query": ""}),
    ("query_knowledge_hub", {"query": "   "}),
    ("query_knowledge_hub", {"query": "test", "top_k": 0}),
    ("query_knowledge_hub", {"query": "test", "top_k": 21}),
    ("get_document_summary", {"doc_id": " "}),
    ("get_document_summary", {}),
])
async def test_invalid_arguments_do_not_reach_tools(http_server, tool_mocks, name, args):
    async with http_server() as url, Client(url) as client:
        result = await client.call_tool(name, args, raise_on_error=False)
        assert result.is_error
        assert all(mock.await_count == 0 for mock in tool_mocks.values())


async def test_tool_failure_and_unexpected_exception_are_masked(http_server, tool_mocks):
    tool_mocks["collections"].return_value = types.CallToolResult(
        content=[types.TextContent(type="text", text="Traceback password=private")], isError=True,
    )
    async with http_server() as url, Client(url) as client:
        result = await client.call_tool("list_collections", {}, raise_on_error=False)
        assert result.is_error and "private" not in str(result.content)
        tool_mocks["collections"].side_effect = RuntimeError("password=private")
        result = await client.call_tool("list_collections", {}, raise_on_error=False)
        assert result.is_error and "private" not in str(result.content)
