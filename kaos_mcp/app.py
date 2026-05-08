from __future__ import annotations

from kaos_core import KaosRuntime
from mcp.server.fastmcp import FastMCP

from kaos_mcp.adapters import (
    ConfigResourceAdapter,
    ContentResourceAdapter,
    ResourceAdapter,
    SessionResourceAdapter,
    TabularResourceAdapter,
    ToolAdapter,
)
from kaos_mcp.adapters.log_bridge import register_set_logging_level, set_log_level
from kaos_mcp.config import KaosMCPSettings


def _log_level_from_string(level: str) -> int:
    """Convert a log level string to a Python logging level int."""
    import logging

    return getattr(logging, level.upper(), logging.INFO)


def create_app(
    runtime: KaosRuntime,
    settings: KaosMCPSettings | None = None,
) -> FastMCP:
    resolved_settings = settings or KaosMCPSettings()
    app = FastMCP(
        name=resolved_settings.name,
        instructions=resolved_settings.instructions,
        debug=resolved_settings.debug,
        host=resolved_settings.host,
        port=resolved_settings.port,
        mount_path=resolved_settings.mount_path,
        streamable_http_path=resolved_settings.streamable_http_path,
        json_response=resolved_settings.json_response,
        stateless_http=resolved_settings.stateless_http,
        log_level=resolved_settings.log_level,
    )
    if resolved_settings.enable_tools:
        ToolAdapter(runtime, resolved_settings).register_runtime_tools(app)
    if resolved_settings.enable_resources:
        ResourceAdapter(runtime, resolved_settings).register_runtime_resources(app)
        ContentResourceAdapter(runtime, resolved_settings).register_content_templates(app)
        TabularResourceAdapter(runtime, resolved_settings).register_tabular_templates(app)
        if resolved_settings.expose_server_config:
            ConfigResourceAdapter(runtime, resolved_settings).register_config_resource(app)
        SessionResourceAdapter(runtime, resolved_settings).register_session_templates(app)

    # Register workflow prompts
    from kaos_mcp.prompts import register_prompts

    register_prompts(app)

    # Initialize dynamic log level from settings and register MCP handler
    set_log_level(_log_level_from_string(resolved_settings.log_level))
    register_set_logging_level(app)

    return app
