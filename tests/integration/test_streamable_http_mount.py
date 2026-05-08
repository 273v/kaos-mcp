from __future__ import annotations

import httpx
import pytest
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from starlette.applications import Starlette
from starlette.routing import Mount


@pytest.mark.integration
async def test_streamable_http_app_mounts_under_subpath(http_server) -> None:
    mounted_app = http_server.streamable_http_app()
    app = Starlette(routes=[Mount("/service", app=mounted_app)])

    def build_client(
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
        auth: httpx.Auth | None = None,
    ) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://127.0.0.1:8000",
            headers=headers,
            timeout=timeout,
            auth=auth,
        )

    async with (
        mounted_app.router.lifespan_context(mounted_app),
        app.router.lifespan_context(app),
        build_client() as client,
        streamable_http_client(
            "http://127.0.0.1:8000/service/mcp",
            terminate_on_close=False,
            http_client=client,
        ) as (read_stream, write_stream, _),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()
        tools = await session.list_tools()
        result = await session.call_tool(
            "kaos-mcp-utility-echo",
            {"message": "http"},
        )

    structured = result.structuredContent
    assert structured is not None

    assert {tool.name for tool in tools.tools} == {
        "kaos-mcp-utility-echo",
        "kaos-mcp-utility-error",
    }
    assert result.isError is False
    assert result.structuredContent == {
        "message": "http",
        "request_id": structured["request_id"],
        "transport": "streamable-http",
    }
