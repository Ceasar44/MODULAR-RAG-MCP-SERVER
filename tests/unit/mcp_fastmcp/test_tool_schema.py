import pytest
from fastmcp import FastMCP

from src.mcp_server.fastmcp_adapter.registry import register_tools


@pytest.mark.asyncio
async def test_public_schema():
    server = FastMCP("schema")
    register_tools(server)
    schemas = {tool.name: tool.parameters for tool in await server.list_tools()}
    query = schemas["query_knowledge_hub"]
    assert query["required"] == ["query"]
    assert query["properties"]["query"]["minLength"] == 1
    top_k = query["properties"]["top_k"]
    assert (top_k["default"], top_k["minimum"], top_k["maximum"]) == (5, 1, 20)
    assert query["properties"]["collection"]["default"] is None
    assert schemas["get_document_summary"]["required"] == ["doc_id"]
    stats = schemas["list_collections"]["properties"]["include_stats"]
    assert stats["type"] == "boolean" and stats["default"] is True
    assert all("ctx" not in schema["properties"] for schema in schemas.values())
