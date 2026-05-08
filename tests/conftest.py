from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from kaos_core import (
    KaosContext,
    KaosRuntime,
    KaosTool,
    ParameterSchema,
    TextContent,
    ToolAnnotations,
    ToolCapability,
    ToolCategory,
    ToolMetadata,
    ToolResult,
)

from kaos_mcp import KaosMCPServer, KaosMCPSettings, create_app


class EchoTool(KaosTool):
    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="kaos-mcp-utility-echo",
            display_name="Echo",
            description="Echo a message back through the MCP boundary.",
            category=ToolCategory.UTILITY,
            capability=ToolCapability.TRANSFORM,
            tags=["test", "echo"],
            input_schema=[
                ParameterSchema(name="message", type="string", description="Message to echo"),
                ParameterSchema(
                    name="repeat",
                    type="integer",
                    description="Repeat count",
                    required=False,
                    default=1,
                ),
            ],
            output_schema={"type": "object"},
            module_name="kaos_mcp.tests",
            version="0.1.0",
            annotations=ToolAnnotations(readOnlyHint=True, humanConfirmationRequired=True),
        )

    async def execute(
        self,
        inputs: dict[str, Any],
        context: KaosContext | None = None,
    ) -> ToolResult:
        repeat = int(inputs.get("repeat", 1))
        message = str(inputs["message"]) * repeat
        if context is not None:
            await context.report_progress(1.0, 2.0, "started")
            await context.report_progress(2.0, 2.0, "done")

        structured = {
            "message": message,
            "request_id": context.metadata.get("request_id") if context else None,
            "transport": context.metadata.get("transport") if context else None,
        }
        # ty doesn't see pydantic field aliases — ``meta`` is a real
        # field on ``ToolResult`` (alias=``_meta``).
        return ToolResult(
            content=[TextContent(text=message)],
            structuredContent=structured,
            meta={"trace_id": context.trace_id if context else None},  # ty: ignore[unknown-argument]
        )


class ErrorTool(KaosTool):
    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="kaos-mcp-utility-error",
            description="Return an MCP-native error result.",
            category=ToolCategory.UTILITY,
            capability=ToolCapability.VALIDATE,
            input_schema=[],
            module_name="kaos_mcp.tests",
            version="0.1.0",
        )

    async def execute(
        self,
        inputs: dict[str, Any],
        context: KaosContext | None = None,
    ) -> ToolResult:
        del inputs, context
        return ToolResult.create_error("synthetic failure", _meta={"kind": "synthetic"})


@pytest.fixture
def runtime() -> KaosRuntime:
    runtime = KaosRuntime()
    runtime.tools.register_tool(EchoTool())
    runtime.tools.register_tool(ErrorTool())
    return runtime


@pytest.fixture
def settings() -> KaosMCPSettings:
    return KaosMCPSettings(name="kaos-mcp-test")


@pytest.fixture
def app(runtime: KaosRuntime, settings: KaosMCPSettings):
    return create_app(runtime, settings)


@pytest.fixture
def server(runtime: KaosRuntime, settings: KaosMCPSettings) -> KaosMCPServer:
    return KaosMCPServer(runtime=runtime, settings=settings)


@pytest.fixture
async def http_server(runtime: KaosRuntime) -> AsyncIterator[KaosMCPServer]:
    yield KaosMCPServer(
        runtime=runtime,
        settings=KaosMCPSettings(
            name="kaos-mcp-http-test",
            transport="streamable-http",
            host="127.0.0.1",
            port=8000,
            mount_path="/service",
        ),
    )
