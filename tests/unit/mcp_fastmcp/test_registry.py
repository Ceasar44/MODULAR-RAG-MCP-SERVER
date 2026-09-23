import pytest
from fastmcp import FastMCP

from src.mcp_server.fastmcp_adapter.registry import get_registered_tool_names, register_tools


@pytest.mark.asyncio
async def test_registers_exactly_three_tools():
    server = FastMCP("test", on_duplicate="error")
    register_tools(server)
    tools = await server.list_tools()
    assert {tool.name for tool in tools} == set(get_registered_tool_names())
    with pytest.raises(Exception, match="already exists"):
        register_tools(server)
