"""Server configuration resource with automatic secret redaction.

audit-02 F3 hardening:

- Always replace secret values with the constant ``"***"`` instead of
  exposing the first / last four characters. Even short prefixes can
  enable targeted lookups against credential dumps.
- Redact by **field name** as well as by ``SecretStr`` type. Matches any
  field whose name contains ``token``, ``password``, ``api_key``,
  ``secret``, ``credential``, or ``auth`` (case-insensitive). Catches
  legacy modules that store credentials as plain ``str``.
- The resource itself is opt-in via ``KaosMCPSettings.expose_server_config``;
  see ``app.create_app``. This file only handles redaction.
"""

from __future__ import annotations

import re
from typing import Any

from kaos_core import KaosRuntime
from pydantic import SecretStr
from pydantic_settings import BaseSettings

from kaos_mcp.config import KaosMCPSettings

REDACTED = "***"

# Field-name patterns that imply a credential, regardless of declared type.
_SECRET_NAME_RE = re.compile(
    r"(?:^|_)(?:token|password|api_?key|secret|credential|auth(?:_?token)?)(?:$|_)",
    re.IGNORECASE,
)


def _is_secret_name(field_name: str) -> bool:
    return bool(_SECRET_NAME_RE.search(field_name))


def _redact_value(value: Any) -> Any:
    """Redact a SecretStr value to the constant REDACTED token."""
    if isinstance(value, SecretStr):
        return REDACTED if value.get_secret_value() else None
    return value


def _redact_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Recursively redact secrets in a settings dict."""
    result: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, dict):
            result[key] = _redact_dict(value)
        elif isinstance(value, SecretStr):
            result[key] = _redact_value(value)
        elif _is_secret_name(key) and value is not None:
            # Field name suggests a credential — redact regardless of type.
            result[key] = REDACTED
        else:
            result[key] = value
    return result


def _dump_settings(settings: BaseSettings) -> dict[str, Any]:
    """Dump settings to dict with secret-named or SecretStr fields redacted."""
    raw: dict[str, Any] = {}
    for field_name in type(settings).model_fields:
        value = getattr(settings, field_name)
        if isinstance(value, SecretStr):
            raw[field_name] = _redact_value(value)
        elif isinstance(value, dict):
            raw[field_name] = _redact_dict(value)
        elif _is_secret_name(field_name) and value is not None:
            raw[field_name] = REDACTED
        else:
            raw[field_name] = value
    return raw


def build_config_dump(
    runtime: KaosRuntime,
    settings: KaosMCPSettings,
) -> dict[str, Any]:
    """Build a redacted config dump for the MCP server."""
    # Server settings
    server_config = _dump_settings(settings)

    # Module settings
    modules: dict[str, Any] = {}
    for module_name, module_settings in runtime.module_settings.items():
        if isinstance(module_settings, BaseSettings):
            modules[module_name] = _dump_settings(module_settings)
        else:
            modules[module_name] = str(module_settings)

    # Tool and resource counts
    tool_count = len(runtime.tools.list_tools()) if hasattr(runtime, "tools") else 0
    resource_count = (
        len(runtime.resources.search_resources()) if hasattr(runtime, "resources") else 0
    )

    return {
        "server": server_config,
        "modules": modules,
        "tools": {"count": tool_count, "enabled": settings.enable_tools},
        "resources": {"count": resource_count, "enabled": settings.enable_resources},
    }


class ConfigResourceAdapter:
    """Registers the kaos://server/config resource."""

    def __init__(self, runtime: KaosRuntime, settings: KaosMCPSettings | None = None) -> None:
        self._runtime = runtime
        self._settings = settings or KaosMCPSettings()

    def register_config_resource(self, app: Any) -> None:
        """Register the server config resource on the FastMCP app."""
        runtime = self._runtime
        settings = self._settings

        @app.resource(
            "kaos://server/config",
            name="server-config",
            title="Server Configuration",
            description="Server configuration with secrets redacted. Useful for debugging.",
            mime_type="application/json",
        )
        async def server_config() -> dict[str, Any]:
            return build_config_dump(runtime, settings)

        del server_config
