import httpx
import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from src.mcp_server.fastmcp_adapter.registry import get_registered_tool_names

pytestmark = pytest.mark.asyncio


async def test_health_without_token_when_mcp_requires_auth(http_server):
    async with http_server(token="correct", path="/custom/mcp") as url:
        async with httpx.AsyncClient() as client:
            response = await client.get(url.removesuffix("/custom/mcp") + "/health")
            assert response.status_code == 200
            assert response.json() == {"status": "ok"}
        # The operational route must not make MCP tools anonymously accessible.
        with pytest.raises(Exception):
            async with Client(StreamableHttpTransport(url), mode="legacy") as client:
                await client.list_tools()


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
