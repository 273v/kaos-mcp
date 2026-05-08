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

    expose_server_config: bool = False
    """If true, register ``kaos://server/config`` for diagnostics. Off by
    default (audit-02 F3): the resource exposes server + module settings
    and should not be reachable from untrusted clients. Secrets are
    redacted in either case, but the resource itself can leak deployment
    topology (paths, hosts, feature flags) — keep it disabled in
    production."""

    max_resource_bytes: int = 10 * 1024 * 1024
    """Maximum bytes returned for any single resource read (audit-02 F4).
    Applies to artifact body, content document, and tabular reads.
    Defaults to 10 MiB."""

    max_range_length: int = 10 * 1024 * 1024
    """Maximum ``length`` accepted on ``kaos://artifacts/{id}/range/{start}/{length}``
    requests (audit-02 F4). Defaults to 10 MiB."""

    max_table_rows: int = 100_000
    """Maximum rows returned per tabular read (audit-02 F4). Defaults to
    100,000 rows."""

    model_config = SettingsConfigDict(
        env_prefix="KAOS_MCP_",
        env_file=".env",
        extra="ignore",
    )
