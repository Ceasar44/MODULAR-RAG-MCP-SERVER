import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from src.mcp_server.fastmcp_adapter.registry import get_registered_tool_names

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_discovery_and_initialize(http_server, mode):
    async with http_server(path="/custom/mcp") as url:
        async with Client(StreamableHttpTransport(url), mode=mode) as client:
            assert {tool.name for tool in await client.list_tools()} == set(get_registered_tool_names())


@pytest.mark.parametrize("token", [None, "wrong", "correct"])
async def test_bearer_auth(http_server, token):
    async with http_server(token="correct") as url:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        client = Client(StreamableHttpTransport(url, headers=headers), mode="legacy")
        if token == "correct":
            async with client:
                assert len(await client.list_tools()) == 3
        else:
            with pytest.raises(Exception):
                async with client:
                    await client.list_tools()
