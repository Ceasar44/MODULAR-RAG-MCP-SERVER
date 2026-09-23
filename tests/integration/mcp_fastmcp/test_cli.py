import asyncio
import os
import socket
import subprocess
import sys

import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport


@pytest.mark.asyncio
async def test_module_entrypoint_with_environment(tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {**os.environ, "RAG_MCP_HOST": "127.0.0.1", "RAG_MCP_PORT": str(port),
           "RAG_MCP_PATH": "/test/mcp", "RAG_MCP_AUTH_ENABLED": "true",
           "RAG_MCP_TOKEN": "cli-test-token", "RAG_MCP_LOG_LEVEL": "ERROR"}
    with (tmp_path / "server.log").open("w+b") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "src.mcp_server.fastmcp_adapter.server"],
            env=env, stdout=log, stderr=log,
        )
        try:
            async def wait_for_listener():
                while process.poll() is None:
                    try:
                        reader, writer = await asyncio.open_connection("127.0.0.1", port)
                        writer.close()
                        await writer.wait_closed()
                        return
                    except OSError:
                        await asyncio.sleep(0.05)
                log.seek(0)
                raise AssertionError(log.read().decode("utf-8", errors="replace"))
            await asyncio.wait_for(wait_for_listener(), 30)
            transport = StreamableHttpTransport(
                f"http://127.0.0.1:{port}/test/mcp",
                headers={"Authorization": "Bearer cli-test-token"},
            )
            async with Client(transport, mode="legacy") as client:
                assert len(await client.list_tools()) == 3
        finally:
            process.terminate()
            try:
                await asyncio.to_thread(process.wait, timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                await asyncio.to_thread(process.wait, timeout=5)
