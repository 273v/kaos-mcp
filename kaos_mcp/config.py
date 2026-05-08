from __future__ import annotations

from typing import Literal

from kaos_core.config import ModuleSettings
from pydantic_settings import SettingsConfigDict


class KaosMCPSettings(ModuleSettings):
    name: str = "kaos-mcp"
    instructions: str | None = None
    transport: Literal["stdio", "streamable-http"] = "stdio"
    host: str = "127.0.0.1"
    port: int = 8000
    mount_path: str = "/"
    streamable_http_path: str = "/mcp"
    debug: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    enable_tools: bool = True
    enable_resources: bool = True
    json_response: bool = True
    stateless_http: bool = True
    list_roots_timeout: float = 2.0
    """Timeout (seconds) for listing client roots during context creation."""

    model_config = SettingsConfigDict(
        env_prefix="KAOS_MCP_",
        env_file=".env",
        extra="ignore",
    )
