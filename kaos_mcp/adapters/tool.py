from __future__ import annotations

import inspect
from typing import Any

from kaos_core import KaosRuntime, KaosTool
from kaos_core.types.metadata import ToolMetadata
from mcp import types
from mcp.server.fastmcp import Context as FastMCPContext
from mcp.server.fastmcp import FastMCP

from kaos_mcp.adapters.context import ContextBridge
from kaos_mcp.adapters.log_bridge import bridge_logs_to_mcp
from kaos_mcp.config import KaosMCPSettings

_TYPE_MAP: dict[str, object] = {
    "array": list[Any],
    "boolean": bool,
    "integer": int,
    "number": float,
    "object": dict[str, Any],
    "string": str,
}


class ToolAdapter:
    def __init__(self, runtime: KaosRuntime, settings: KaosMCPSettings) -> None:
        self._runtime = runtime
        self._settings = settings
        self._bridge = ContextBridge(runtime, settings)

    def register_runtime_tools(self, app: FastMCP) -> int:
        count = 0
        for tool in self._runtime.tools.list_tool_objects():
            self.register_tool(app, tool)
            count += 1
        return count

    def register_tool(self, app: FastMCP, tool: KaosTool) -> None:
        handler = self.build_tool_handler(tool)
        app.add_tool(
            handler,
            name=tool.metadata.name,
            title=tool.metadata.display_name,
            description=tool.metadata.description,
            annotations=self.to_fastmcp_annotations(tool.metadata),
            icons=self.to_fastmcp_icons(tool.metadata),
            meta=self.to_fastmcp_meta(tool.metadata),
            structured_output=False,
        )

    def build_tool_handler(self, tool: KaosTool) -> Any:
        async def handler(**kwargs: Any) -> types.CallToolResult:
            context = kwargs.pop("ctx")
            async with bridge_logs_to_mcp(context):
                kaos_context = await self._bridge.create_kaos_context(context)
                # The FastMCP signature we synthesize in `_build_signature`
                # gives every optional parameter a `None` default, so a
                # caller that omits an optional param still arrives here
                # with `name=None` in `kwargs`. The kaos-core type-validator
                # checks every key in `inputs.items()`, and `None` against
                # a declared `array` / `object` / `string` schema fires
                # "expected <type>, got NoneType". Drop `None` values for
                # fields that are not required so missing-optional and
                # explicit-`None` get the same "treat as unset" semantics.
                required_inputs = {
                    parameter.name for parameter in tool.metadata.input_schema if parameter.required
                }
                filtered_inputs = {
                    name: value
                    for name, value in kwargs.items()
                    if value is not None or name in required_inputs
                }
                tool.validate_inputs(filtered_inputs)
                result = await tool.execute(filtered_inputs, context=kaos_context)
                return types.CallToolResult(**result.to_mcp_dict())

        handler.__name__ = tool.metadata.name.replace("-", "_")
        handler.__doc__ = tool.metadata.description
        handler.__annotations__ = self._build_annotations(tool.metadata)
        handler.__signature__ = self._build_signature(tool.metadata)  # ty: ignore[unresolved-attribute]
        return handler

    def to_fastmcp_annotations(self, metadata: ToolMetadata) -> types.ToolAnnotations | None:
        if metadata.annotations is None:
            return None

        payload = metadata.annotations.model_dump(
            exclude_none=True,
            exclude={"humanConfirmationRequired"},
        )
        return types.ToolAnnotations(**payload)

    def to_fastmcp_icons(self, metadata: ToolMetadata) -> list[types.Icon] | None:
        if metadata.icon is None:
            return None
        return [types.Icon(src=metadata.icon)]

    def to_fastmcp_meta(self, metadata: ToolMetadata) -> dict[str, Any]:
        meta: dict[str, Any] = {
            "kaos/capability": metadata.capability.value,
            "kaos/category": metadata.category.value,
            "kaos/module_name": metadata.module_name,
            "kaos/supports_tasks": metadata.supports_tasks,
            "kaos/version": metadata.version,
        }
        if metadata.annotations is not None and metadata.annotations.humanConfirmationRequired:
            meta["kaos/human_confirmation_required"] = True
        if metadata.output_schema is not None:
            meta["kaos/output_schema"] = metadata.output_schema
        return meta

    def _build_annotations(self, metadata: ToolMetadata) -> dict[str, object]:
        annotations = {
            parameter.name: self._annotation_for(parameter.type)
            for parameter in metadata.input_schema
        }
        annotations["ctx"] = FastMCPContext
        return annotations

    def _build_signature(self, metadata: ToolMetadata) -> inspect.Signature:
        parameters = [
            inspect.Parameter(
                name=parameter.name,
                kind=inspect.Parameter.KEYWORD_ONLY,
                annotation=self._annotation_for(parameter.type),
                default=self._default_for(parameter),
            )
            for parameter in metadata.input_schema
        ]
        parameters.append(
            inspect.Parameter(
                name="ctx",
                kind=inspect.Parameter.KEYWORD_ONLY,
                annotation=FastMCPContext,
            )
        )
        return inspect.Signature(parameters=parameters)

    def _annotation_for(self, schema_type: str) -> object:
        return _TYPE_MAP.get(schema_type, Any)

    def _default_for(self, parameter: Any) -> Any:
        if parameter.required:
            return inspect.Signature.empty
        return parameter.default if parameter.default is not None else None
