"""Tests for the server configuration resource with secret redaction."""

from __future__ import annotations

from typing import Any

import pytest
from kaos_core import KaosRuntime
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from kaos_mcp.adapters.config_resource import (
    _dump_settings,
    _redact_dict,
    _redact_value,
    build_config_dump,
)
from kaos_mcp.config import KaosMCPSettings

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class ApiSettings(BaseSettings):
    """Test settings class with SecretStr fields."""

    api_key: SecretStr = SecretStr("")
    api_url: str = "https://api.example.com"
    nested: dict[str, Any] = {}

    model_config = SettingsConfigDict(env_prefix="TEST_API_", extra="ignore")


# ---------------------------------------------------------------------------
# _redact_value
# ---------------------------------------------------------------------------


class TestRedactValue:
    def test_empty_secret_returns_none(self) -> None:
        assert _redact_value(SecretStr("")) is None

    def test_short_secret_returns_stars(self) -> None:
        assert _redact_value(SecretStr("abc")) == "***"

    def test_eight_char_secret_returns_stars(self) -> None:
        assert _redact_value(SecretStr("12345678")) == "***"

    def test_long_secret_shows_prefix_and_suffix(self) -> None:
        result = _redact_value(SecretStr("abcdefghijklmnop"))
        assert result == "abcd...mnop"

    def test_non_secret_passes_through(self) -> None:
        assert _redact_value("plain") == "plain"
        assert _redact_value(42) == 42
        assert _redact_value(None) is None


# ---------------------------------------------------------------------------
# _redact_dict
# ---------------------------------------------------------------------------


class TestRedactDict:
    def test_flat_dict_no_secrets(self) -> None:
        data = {"key": "value", "num": 123}
        assert _redact_dict(data) == {"key": "value", "num": 123}

    def test_dict_with_secret_str(self) -> None:
        data = {"token": SecretStr("supersecrettoken123")}
        result = _redact_dict(data)
        assert result["token"] == "supe...n123"

    def test_nested_dict_with_secret(self) -> None:
        data = {
            "outer": {
                "inner_secret": SecretStr("abcdefghijklmnop"),
                "inner_plain": "hello",
            }
        }
        result = _redact_dict(data)
        assert result["outer"]["inner_secret"] == "abcd...mnop"
        assert result["outer"]["inner_plain"] == "hello"

    def test_empty_dict(self) -> None:
        assert _redact_dict({}) == {}


# ---------------------------------------------------------------------------
# _dump_settings
# ---------------------------------------------------------------------------


class TestDumpSettings:
    def test_dumps_kaos_mcp_settings(self) -> None:
        settings = KaosMCPSettings(name="test-server", debug=True)
        dumped = _dump_settings(settings)
        assert dumped["name"] == "test-server"
        assert dumped["debug"] is True
        assert dumped["enable_tools"] is True

    def test_redacts_secret_str_field(self) -> None:
        settings = ApiSettings(api_key=SecretStr("my-long-api-key-here"))
        dumped = _dump_settings(settings)
        assert dumped["api_key"] == "my-l...here"
        assert dumped["api_url"] == "https://api.example.com"

    def test_redacts_dict_field_with_secrets(self) -> None:
        settings = ApiSettings(nested={"token": SecretStr("abcdefghijklmnop"), "label": "prod"})
        dumped = _dump_settings(settings)
        assert dumped["nested"]["token"] == "abcd...mnop"
        assert dumped["nested"]["label"] == "prod"


# ---------------------------------------------------------------------------
# build_config_dump
# ---------------------------------------------------------------------------


class TestBuildConfigDump:
    def test_basic_structure(self) -> None:
        runtime = KaosRuntime()
        settings = KaosMCPSettings(name="cfg-test")
        dump = build_config_dump(runtime, settings)

        assert "server" in dump
        assert "modules" in dump
        assert "tools" in dump
        assert "resources" in dump
        assert dump["server"]["name"] == "cfg-test"
        assert dump["tools"]["enabled"] is True
        assert dump["resources"]["enabled"] is True

    def test_empty_module_settings(self) -> None:
        runtime = KaosRuntime()
        settings = KaosMCPSettings()
        dump = build_config_dump(runtime, settings)

        assert dump["modules"] == {}

    def test_module_settings_with_base_settings(self) -> None:
        runtime = KaosRuntime()
        runtime.module_settings["api"] = ApiSettings(
            api_key=SecretStr("long-secret-key-value"),
            api_url="https://test.example.com",
        )
        settings = KaosMCPSettings()
        dump = build_config_dump(runtime, settings)

        assert "api" in dump["modules"]
        mod = dump["modules"]["api"]
        assert mod["api_key"] == "long...alue"
        assert mod["api_url"] == "https://test.example.com"

    def test_module_settings_with_non_settings_object(self) -> None:
        runtime = KaosRuntime()
        runtime.module_settings["custom"] = {"raw": "config"}
        settings = KaosMCPSettings()
        dump = build_config_dump(runtime, settings)

        assert dump["modules"]["custom"] == "{'raw': 'config'}"

    def test_tool_and_resource_counts(self) -> None:
        runtime = KaosRuntime()
        settings = KaosMCPSettings()
        dump = build_config_dump(runtime, settings)

        assert dump["tools"]["count"] == 0
        assert dump["resources"]["count"] == 0

    def test_disabled_tools_and_resources(self) -> None:
        runtime = KaosRuntime()
        settings = KaosMCPSettings(enable_tools=False, enable_resources=False)
        dump = build_config_dump(runtime, settings)

        assert dump["tools"]["enabled"] is False
        assert dump["resources"]["enabled"] is False


# ---------------------------------------------------------------------------
# ConfigResourceAdapter registration
# ---------------------------------------------------------------------------


class TestConfigResourceAdapter:
    @pytest.mark.unit
    async def test_resource_registered_and_readable(self) -> None:
        from kaos_mcp import create_app

        runtime = KaosRuntime()
        settings = KaosMCPSettings(name="adapter-test")
        app = create_app(runtime, settings)

        resources = await app.list_resources()
        config_resource = [r for r in resources if str(r.uri) == "kaos://server/config"]
        assert len(config_resource) == 1
        assert config_resource[0].name == "server-config"
        assert config_resource[0].mimeType == "application/json"

    @pytest.mark.unit
    async def test_resource_returns_valid_dump(self) -> None:
        from kaos_mcp import create_app

        runtime = KaosRuntime()
        settings = KaosMCPSettings(name="dump-test")
        app = create_app(runtime, settings)

        contents = list(await app.read_resource("kaos://server/config"))
        assert len(contents) > 0
        # The resource returns JSON-serialized dict
        import json

        data = json.loads(contents[0].content)
        assert data["server"]["name"] == "dump-test"
        assert "modules" in data
        assert "tools" in data
        assert "resources" in data
