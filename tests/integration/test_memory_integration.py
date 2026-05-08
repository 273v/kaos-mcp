from __future__ import annotations

from typing import Any

import pytest
from kaos_core import KaosContext, KaosRuntime, KaosSettings
from kaos_core.types.enums import StorageBackend
from kaos_core.vfs import VFSConfig, VirtualFileSystem
from mcp import types
from mcp.client.session import ListRootsFnT
from mcp.shared.exceptions import McpError
from mcp.shared.memory import create_connected_server_and_client_session
from pydantic import AnyUrl

from kaos_mcp import create_app


@pytest.mark.integration
async def test_memory_client_call_preserves_structured_tool_result(app) -> None:
    progress_updates: list[tuple[float, float | None, str | None]] = []

    async with create_connected_server_and_client_session(app) as session:
        tools = await session.list_tools()
        assert {tool.name for tool in tools.tools} == {
            "kaos-mcp-utility-echo",
            "kaos-mcp-utility-error",
        }

        result = await session.call_tool(
            "kaos-mcp-utility-echo",
            {"message": "hi", "repeat": 2},
            progress_callback=lambda progress, total, message: progress_updates.append(  # ty: ignore[invalid-argument-type]
                (progress, total, message)
            ),
            meta={"progressToken": "progress-1"},
        )

    structured = result.structuredContent
    assert structured is not None
    content_block = result.content[0].model_dump(mode="json")

    assert result.isError is False
    assert content_block["text"] == "hihi"
    assert result.structuredContent == {
        "message": "hihi",
        "request_id": structured["request_id"],
        "transport": "stdio",
    }
    assert result.meta == {"trace_id": structured["request_id"]}
    assert progress_updates == [(1.0, 2.0, "started"), (2.0, 2.0, "done")]


@pytest.mark.integration
async def test_memory_client_error_result_stays_mcp_shaped(app) -> None:
    async with create_connected_server_and_client_session(app) as session:
        result = await session.call_tool("kaos-mcp-utility-error")

    content_block = result.content[0].model_dump(mode="json")

    assert result.isError is True
    assert content_block["text"] == "synthetic failure"
    assert result.meta == {"kind": "synthetic"}


@pytest.mark.integration
async def test_memory_client_reads_binary_artifact_and_reports_missing_handles(
    runtime, settings
) -> None:
    context = KaosContext.create(session_id="binary-session", runtime=runtime)
    payload = b"\x00\x01\x02ABC\xff"
    await context.get_vfs_path("artifacts/payload.bin").write_bytes(payload)
    manifest = await runtime.artifacts.create_from_path(
        "artifacts/payload.bin",
        context_id=context.session_id,
        session_id=context.session_id,
        name="payload",
        mime_type="application/octet-stream",
    )
    app = create_app(runtime, settings)

    async with create_connected_server_and_client_session(app) as session:
        result = await session.read_resource(AnyUrl(manifest.body_uri))
        with pytest.raises(McpError, match="Unknown artifact"):
            await session.read_resource(AnyUrl("kaos://artifacts/missing/body"))

    first = result.contents[0]
    assert isinstance(first, types.BlobResourceContents)
    assert first.blob == "AAECQUJD/w=="
    assert first.mimeType == "application/octet-stream"


@pytest.mark.integration
async def test_memory_client_respects_roots_and_chunked_artifact_reads(tmp_path) -> None:
    settings = KaosSettings(artifact_inline_read_max_bytes=16, artifact_chunk_size_bytes=8)
    runtime = KaosRuntime(config=settings)
    runtime.vfs = VirtualFileSystem(
        VFSConfig(default_backend=StorageBackend.DISK, disk_base_path=tmp_path / "vfs")
    )
    runtime.artifacts = runtime.artifacts.__class__(
        runtime.vfs,
        manifest_context_id=settings.artifact_manifest_context_id,
        manifest_prefix=settings.artifact_manifest_prefix,
        max_inline_read_bytes=settings.artifact_inline_read_max_bytes,
        default_chunk_size=settings.artifact_chunk_size_bytes,
        temporary_ttl_seconds=settings.artifact_temporary_ttl_seconds,
    )

    session_id = "rooted-session"
    payload = ("0123456789abcdef" * 4).encode("utf-8")
    context = KaosContext.create(session_id=session_id, runtime=runtime)
    await context.get_vfs_path("artifacts/large.txt").write_bytes(payload)
    manifest = await runtime.artifacts.create_from_path(
        "artifacts/large.txt",
        context_id=session_id,
        session_id=session_id,
        name="large",
        mime_type="text/plain",
    )
    app = create_app(runtime)

    async def _allowed_roots(
        _ctx: Any,
    ) -> types.ListRootsResult | types.ErrorData:
        return types.ListRootsResult(
            roots=[
                types.Root(uri=(tmp_path / "vfs" / session_id).resolve().as_uri(), name="allowed")
            ]
        )

    allowed_roots: ListRootsFnT = _allowed_roots  # ty: ignore[invalid-assignment]

    async def _blocked_roots(
        _ctx: Any,
    ) -> types.ListRootsResult | types.ErrorData:
        return types.ListRootsResult(
            roots=[types.Root(uri=(tmp_path / "blocked").resolve().as_uri(), name="blocked")]
        )

    blocked_roots: ListRootsFnT = _blocked_roots  # ty: ignore[invalid-assignment]

    async with create_connected_server_and_client_session(
        app,
        list_roots_callback=allowed_roots,
    ) as session:
        with pytest.raises(McpError, match="inline read limit"):
            await session.read_resource(AnyUrl(manifest.body_uri))
        chunk = await session.read_resource(AnyUrl(manifest.chunk_uri(1)))
        range_result = await session.read_resource(AnyUrl(manifest.range_uri(4, 8)))

    async with create_connected_server_and_client_session(
        app,
        list_roots_callback=blocked_roots,
    ) as session:
        with pytest.raises(McpError, match="roots policy"):
            await session.read_resource(AnyUrl(manifest.manifest_uri))

    chunk_first = chunk.contents[0]
    assert isinstance(chunk_first, types.BlobResourceContents)
    assert chunk_first.blob == "ODlhYmNkZWY="
    range_first = range_result.contents[0]
    assert isinstance(range_first, types.BlobResourceContents)
    assert range_first.blob == "NDU2Nzg5YWI="
