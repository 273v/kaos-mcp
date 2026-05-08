from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

import pydantic_core
from kaos_core import KaosContext, KaosRuntime
from kaos_core.types.metadata import ResourceMetadata
from mcp.server.fastmcp import Context as FastMCPContext
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ResourceError as FastMCPResourceError
from mcp.server.fastmcp.resources import Resource
from pydantic import AnyUrl, Field, validate_call

from kaos_mcp.adapters._error_handling import resource_error_from_exception
from kaos_mcp.adapters.context import ContextBridge, caller_session_id
from kaos_mcp.config import KaosMCPSettings


class NormalizedFunctionResource(Resource):
    reader: Callable[[], Any] = Field(exclude=True)

    async def read(self) -> str | bytes:
        try:
            result = self.reader()
            if inspect.iscoroutine(result):
                result = await result

            if isinstance(result, bytes):
                return result
            if isinstance(result, str):
                return result
            return pydantic_core.to_json(result, fallback=str, indent=2).decode()
        except FastMCPResourceError:
            raise
        except Exception as exc:
            raise resource_error_from_exception(exc) from exc

    @classmethod
    def from_function(
        cls,
        fn: Callable[..., Any],
        *,
        uri: str,
        name: str,
        title: str | None = None,
        description: str | None = None,
        mime_type: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> NormalizedFunctionResource:
        return cls(
            uri=AnyUrl(uri),
            name=name,
            title=title,
            description=description or fn.__doc__ or "",
            mime_type=mime_type or "text/plain",
            reader=validate_call(fn),
            meta=meta,
        )


class ResourceAdapter:
    def __init__(self, runtime: KaosRuntime, settings: KaosMCPSettings | None = None) -> None:
        self._runtime = runtime
        self._settings = settings or KaosMCPSettings()
        self._bridge = ContextBridge(runtime, self._settings)

    def register_runtime_resources(self, app: FastMCP) -> int:
        count = 0
        for metadata in self._runtime.resources.search_resources():
            app.add_resource(self._build_function_resource(metadata))
            count += 1
        self._register_artifact_templates(app)
        return count + 4

    def _wrap_resource_error(self, uri: str, exc: Exception) -> FastMCPResourceError:
        return resource_error_from_exception(exc, context=uri)

    def _build_function_resource(self, metadata: ResourceMetadata) -> NormalizedFunctionResource:
        async def read_resource() -> Any:
            try:
                context = KaosContext.create(runtime=self._runtime)
                return await self._runtime.resources.get_resource(
                    metadata.uri, use_cache=False, context=context
                )
            except Exception as exc:
                raise self._wrap_resource_error(metadata.uri, exc) from exc

        return NormalizedFunctionResource.from_function(
            read_resource,
            uri=metadata.uri,
            name=metadata.name,
            title=metadata.name,
            description=metadata.description,
            mime_type=metadata.mime_type,
            meta={
                "kaos/module_name": metadata.provider_module,
                "kaos/resource_type": metadata.resource_type.value,
                "kaos/version": metadata.version,
            },
        )

    def _register_artifact_templates(self, app: FastMCP) -> None:
        @app.resource(
            "kaos://artifacts/{artifact_id}/manifest",
            name="artifact-manifest",
            title="Artifact Manifest",
            description="Resolve an artifact manifest by artifact id.",
            mime_type="application/json",
        )
        async def artifact_manifest(artifact_id: str, ctx: FastMCPContext) -> str:
            try:
                roots = await self._bridge.list_roots(ctx)
                payload = await self._runtime.artifacts.read_uri(
                    f"kaos://artifacts/{artifact_id}/manifest",
                    roots=roots,
                    caller_session_id=caller_session_id(ctx),
                )
                if isinstance(payload, bytes):
                    return payload.decode("utf-8", errors="replace")
                return payload
            except Exception as exc:
                raise self._wrap_resource_error(
                    f"kaos://artifacts/{artifact_id}/manifest",
                    exc,
                ) from exc

        @app.resource(
            "kaos://artifacts/{artifact_id}/body",
            name="artifact-body",
            title="Artifact Body",
            description="Resolve the artifact body by artifact id.",
            mime_type="application/octet-stream",
        )
        async def artifact_body(artifact_id: str, ctx: FastMCPContext) -> str | bytes:
            try:
                roots = await self._bridge.list_roots(ctx)
                return await self._runtime.artifacts.read_uri(
                    f"kaos://artifacts/{artifact_id}/body",
                    roots=roots,
                    caller_session_id=caller_session_id(ctx),
                )
            except Exception as exc:
                raise self._wrap_resource_error(
                    f"kaos://artifacts/{artifact_id}/body",
                    exc,
                ) from exc

        @app.resource(
            "kaos://artifacts/{artifact_id}/chunk/{chunk_index}",
            name="artifact-chunk",
            title="Artifact Chunk",
            description="Read a fixed-size chunk from an artifact body.",
            mime_type="application/octet-stream",
        )
        async def artifact_chunk(
            artifact_id: str,
            chunk_index: int,
            ctx: FastMCPContext,
        ) -> bytes:
            try:
                roots = await self._bridge.list_roots(ctx)
                return await self._runtime.artifacts.read_chunk(
                    artifact_id,
                    chunk_index=chunk_index,
                    chunk_size=self._runtime.settings.artifact_chunk_size_bytes,
                    roots=roots,
                    caller_session_id=caller_session_id(ctx),
                )
            except Exception as exc:
                raise self._wrap_resource_error(
                    f"kaos://artifacts/{artifact_id}/chunk/{chunk_index}",
                    exc,
                ) from exc

        @app.resource(
            "kaos://artifacts/{artifact_id}/range/{start}/{length}",
            name="artifact-range",
            title="Artifact Range",
            description="Read a byte range from an artifact body.",
            mime_type="application/octet-stream",
        )
        async def artifact_range(
            artifact_id: str,
            start: int,
            length: int,
            ctx: FastMCPContext,
        ) -> bytes:
            try:
                # F4: cap caller-supplied length so a single request cannot
                # request an unbounded byte range.
                if length > self._settings.max_range_length:
                    raise FastMCPResourceError(
                        f"kaos://artifacts/{artifact_id}/range/{start}/{length}: "
                        f"length {length} exceeds max_range_length "
                        f"{self._settings.max_range_length}"
                    )
                roots = await self._bridge.list_roots(ctx)
                return await self._runtime.artifacts.read_body(
                    artifact_id,
                    start=start,
                    length=length,
                    roots=roots,
                    max_bytes=length,
                    caller_session_id=caller_session_id(ctx),
                )
            except Exception as exc:
                raise self._wrap_resource_error(
                    f"kaos://artifacts/{artifact_id}/range/{start}/{length}",
                    exc,
                ) from exc

        del artifact_manifest, artifact_body, artifact_chunk, artifact_range
