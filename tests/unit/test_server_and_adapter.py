from __future__ import annotations

import pytest
from kaos_core import (
    KaosContext,
    KaosResource,
    KaosRuntime,
    KaosSettings,
    ResourceMetadata,
    ResourceType,
)
from kaos_core.types.enums import StorageBackend
from kaos_core.vfs import VFSConfig, VirtualFileSystem
from mcp.server.fastmcp.exceptions import ResourceError as FastMCPResourceError

from kaos_mcp import create_app
from kaos_mcp.server import KaosMCPServer


class StaticResource(KaosResource):
    @property
    def metadata(self) -> ResourceMetadata:
        return ResourceMetadata(
            uri="kaos://tests/static",
            name="static",
            description="Static test resource",
            resource_type=ResourceType.DOCUMENT,
            mime_type="text/plain",
            provider_module="kaos_mcp.tests",
            version="0.1.0",
        )

    async def read(self, context=None) -> str:
        del context
        return "resource body"

    async def get_metadata(self, context=None) -> dict[str, str]:
        del context
        return {"kind": "static"}


class FailingResource(KaosResource):
    @property
    def metadata(self) -> ResourceMetadata:
        return ResourceMetadata(
            uri="kaos://tests/network-timeout",
            name="network-timeout",
            description="Simulated failing network-backed resource",
            resource_type=ResourceType.DOCUMENT,
            mime_type="text/plain",
            provider_module="kaos_mcp.tests",
            version="0.1.0",
        )

    async def read(self, context=None) -> str:
        del context
        raise TimeoutError("upstream network timed out")

    async def get_metadata(self, context=None) -> dict[str, str]:
        del context
        return {"kind": "failing"}


@pytest.mark.unit
async def test_create_app_registers_tool_metadata(app) -> None:
    tools = await app.list_tools()
    descriptor = next(tool for tool in tools if tool.name == "kaos-mcp-utility-echo")

    assert descriptor.title == "Echo"
    assert descriptor.description == "Echo a message back through the MCP boundary."
    assert descriptor.inputSchema["properties"]["message"]["type"] == "string"
    assert descriptor.inputSchema["properties"]["repeat"]["type"] == "integer"
    assert descriptor.annotations is not None
    assert descriptor.annotations.readOnlyHint is True
    assert descriptor.meta == {
        "kaos/capability": "transform",
        "kaos/category": "utility",
        "kaos/human_confirmation_required": True,
        "kaos/module_name": "kaos_mcp.tests",
        "kaos/output_schema": {"type": "object"},
        "kaos/supports_tasks": False,
        "kaos/version": "0.1.0",
    }


@pytest.mark.unit
async def test_create_app_registers_runtime_resources_and_artifact_templates(
    runtime, settings
) -> None:
    runtime.resources.register_resource(StaticResource())

    context = KaosContext.create(session_id="artifact-session", runtime=runtime)
    path = context.get_vfs_path("artifacts/demo.txt")
    await path.write_text("artifact body")
    manifest = await runtime.artifacts.create_from_path(
        "artifacts/demo.txt",
        context_id=context.session_id,
        session_id=context.session_id,
        name="demo artifact",
        mime_type="text/plain",
    )

    app = create_app(runtime, settings)
    resources = await app.list_resources()
    templates = await app.list_resource_templates()
    static_contents = list(await app.read_resource("kaos://tests/static"))
    manifest_contents = list(await app.read_resource(manifest.manifest_uri))
    body_contents = list(await app.read_resource(manifest.body_uri))

    assert any(str(resource.uri) == "kaos://tests/static" for resource in resources)
    template_uris = {template.uriTemplate for template in templates}
    # Artifact templates
    assert "kaos://artifacts/{artifact_id}/body" in template_uris
    assert "kaos://artifacts/{artifact_id}/chunk/{chunk_index}" in template_uris
    assert "kaos://artifacts/{artifact_id}/manifest" in template_uris
    assert "kaos://artifacts/{artifact_id}/range/{start}/{length}" in template_uris
    # Content document templates
    assert "kaos://content/{artifact_id}" in template_uris
    assert "kaos://content/{artifact_id}/markdown" in template_uris
    assert "kaos://content/{artifact_id}/metadata" in template_uris
    assert "kaos://content/{artifact_id}/outline" in template_uris
    # Session templates
    assert "kaos://session/{session_id}/artifacts" in template_uris
    assert static_contents[0].content == "resource body"
    assert manifest.artifact_id in manifest_contents[0].content
    assert body_contents[0].content == "artifact body"


@pytest.mark.unit
async def test_session_artifact_index_lists_session_artifacts(runtime, settings) -> None:
    """Session artifact index resource returns all artifacts for a session."""
    import json
    from uuid import uuid4

    session_id = f"session-index-{uuid4().hex[:8]}"
    context = KaosContext.create(session_id=session_id, runtime=runtime)

    # Create two artifacts in the same session
    for i in range(2):
        vfs_path = f"artifacts/{session_id}/doc{i}.txt"
        path = context.get_vfs_path(vfs_path)
        await path.write_text(f"content {i}")
        await runtime.artifacts.create_from_path(
            vfs_path,
            context_id=session_id,
            session_id=session_id,
            name=f"doc-{i}",
            mime_type="text/plain",
        )

    app = create_app(runtime, settings)
    contents = list(await app.read_resource(f"kaos://session/{session_id}/artifacts"))
    data = json.loads(contents[0].content)

    assert data["session_id"] == session_id
    assert data["count"] == 2
    assert len(data["artifacts"]) == 2
    assert {a["name"] for a in data["artifacts"]} == {"doc-0", "doc-1"}
    # Each artifact should have body_uri
    for artifact in data["artifacts"]:
        assert artifact["body_uri"].startswith("kaos://artifacts/")


@pytest.mark.unit
async def test_session_artifact_index_empty_session(runtime, settings) -> None:
    """Session artifact index returns empty list for unknown session."""
    import json

    app = create_app(runtime, settings)
    contents = list(await app.read_resource("kaos://session/nonexistent/artifacts"))
    data = json.loads(contents[0].content)

    assert data["count"] == 0
    assert data["artifacts"] == []


@pytest.mark.unit
async def test_artifact_body_supports_binary_payloads_and_missing_handles(
    runtime, settings
) -> None:
    context = KaosContext.create(session_id="binary-session", runtime=runtime)
    path = context.get_vfs_path("artifacts/payload.bin")
    payload = b"\x00\x01\x02ABC\xff"
    await path.write_bytes(payload)
    manifest = await runtime.artifacts.create_from_path(
        "artifacts/payload.bin",
        context_id=context.session_id,
        session_id=context.session_id,
        name="payload",
        mime_type="application/octet-stream",
    )

    app = create_app(runtime, settings)
    body_contents = list(await app.read_resource(manifest.body_uri))

    assert body_contents[0].content == payload
    assert body_contents[0].mime_type == "application/octet-stream"

    with pytest.raises(ValueError, match="Unknown artifact"):
        await app.read_resource("kaos://artifacts/missing/body")


@pytest.mark.unit
async def test_large_artifacts_require_chunk_or_range_resources(tmp_path) -> None:
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

    context = KaosContext.create(session_id="large-session", runtime=runtime)
    payload = ("0123456789abcdef" * 4).encode("utf-8")
    await context.get_vfs_path("artifacts/large.txt").write_bytes(payload)
    manifest = await runtime.artifacts.create_from_path(
        "artifacts/large.txt",
        context_id=context.session_id,
        session_id=context.session_id,
        name="large",
        mime_type="text/plain",
    )
    app = create_app(runtime)

    with pytest.raises(ValueError, match="inline read limit"):
        await app.read_resource(manifest.body_uri)

    chunk_contents = list(await app.read_resource(manifest.chunk_uri(1)))
    range_contents = list(await app.read_resource(manifest.range_uri(4, 8)))

    assert chunk_contents[0].content == payload[8:16]
    assert range_contents[0].content == payload[4:12]


@pytest.mark.unit
async def test_runtime_resource_failures_surface_with_context(runtime, settings) -> None:
    runtime.resources.register_resource(FailingResource())
    app = create_app(runtime, settings)

    with pytest.raises(FastMCPResourceError, match="network timed out"):
        await app.read_resource("kaos://tests/network-timeout")


def test_run_stdio_delegates_to_fastmcp(monkeypatch, runtime, settings) -> None:
    calls: list[tuple[str, str | None]] = []

    class FakeApp:
        def run(self, transport: str = "stdio", mount_path: str | None = None) -> None:
            calls.append((transport, mount_path))

    server = KaosMCPServer(runtime=runtime, settings=settings)
    monkeypatch.setattr(server, "build_app", lambda: FakeApp())

    server.run_stdio()

    assert calls == [("stdio", "/")]


def test_run_streamable_http_delegates_to_fastmcp(monkeypatch, runtime, settings) -> None:
    calls: list[tuple[str, str | None]] = []

    class FakeApp:
        def run(self, transport: str = "stdio", mount_path: str | None = None) -> None:
            calls.append((transport, mount_path))

    server = KaosMCPServer(
        runtime=runtime,
        settings=settings.model_copy(update={"transport": "streamable-http"}),
    )
    monkeypatch.setattr(server, "build_app", lambda: FakeApp())

    server.run_streamable_http()

    assert calls == [("streamable-http", "/")]
