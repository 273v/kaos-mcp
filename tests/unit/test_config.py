from __future__ import annotations

from kaos_mcp import KaosMCPSettings


def test_settings_defaults() -> None:
    settings = KaosMCPSettings()

    assert settings.transport == "stdio"
    assert settings.json_response is True
    assert settings.stateless_http is True
    assert settings.streamable_http_path == "/mcp"
    assert settings.list_roots_timeout == 2.0


def test_settings_honors_environment(monkeypatch) -> None:
    monkeypatch.setenv("KAOS_MCP_NAME", "env-server")
    monkeypatch.setenv("KAOS_MCP_TRANSPORT", "streamable-http")

    settings = KaosMCPSettings()

    assert settings.name == "env-server"
    assert settings.transport == "streamable-http"


def test_list_roots_timeout_env_override(monkeypatch) -> None:
    monkeypatch.setenv("KAOS_MCP_LIST_ROOTS_TIMEOUT", "5.0")

    settings = KaosMCPSettings()

    assert settings.list_roots_timeout == 5.0
