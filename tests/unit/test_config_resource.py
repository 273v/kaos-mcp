"""Tests for the server configuration resource with secret redaction.

audit-02 F3:
- The resource is opt-in via ``KaosMCPSettings.expose_server_config``;
  default is False.
- Redaction is constant ``"***"`` (no prefix/suffix disclosure).
- Field-name redaction triggers on ``token``, ``password``, ``api_key``,
  ``secret``, ``credential``, ``auth`` regardless of declared type.
"""

from __future__ import annotations

from typing import Any

import pytest
from kaos_core import KaosRuntime
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from kaos_mcp.adapters.config_resource import (
    REDACTED,
    _dump_settings,
    _is_secret_name,
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


class PlainStrSecretSettings(BaseSettings):
    """Legacy-shape settings: credentials stored as plain strings."""

    api_key: str = ""
    auth_token: str = ""
    user_password: str = ""
    plain_value: str = "hello"
    nested_blob: dict[str, Any] = {}

    model_config = SettingsConfigDict(env_prefix="TEST_LEGACY_", extra="ignore")


# ---------------------------------------------------------------------------
# _is_secret_name
# ---------------------------------------------------------------------------


class TestIsSecretName:
    @pytest.mark.parametrize(
        "field",
        [
            "api_key",
            "API_KEY",
            "apikey",
            "auth_token",
            "auth",
            "token",
            "password",
            "user_password",
            "secret",
            "client_secret",
            "credential",
            "db_credential",
        ],
    )
    def test_credential_names_match(self, field: str) -> None:
        assert _is_secret_name(field) is True

    @pytest.mark.parametrize(
        "field",
        ["api_url", "host", "port", "name", "debug", "transport", "log_level"],
    )
    def test_plain_names_do_not_match(self, field: str) -> None:
        assert _is_secret_name(field) is False


# ---------------------------------------------------------------------------
# _redact_value — always constant
# ---------------------------------------------------------------------------


class TestRedactValue:
    def test_empty_secret_returns_none(self) -> None:
        assert _redact_value(SecretStr("")) is None

    def test_short_secret_returns_constant(self) -> None:
        assert _redact_value(SecretStr("abc")) == REDACTED

    def test_long_secret_returns_constant_no_partial(self) -> None:
        # F3: previously emitted "abcd...mnop"; now must be the constant.
        result = _redact_value(SecretStr("abcdefghijklmnop"))
        assert result == REDACTED
        assert "abcd" not in str(result)
        assert "mnop" not in str(result)

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
        assert _redact_dict(data) == {"token": REDACTED}

    def test_dict_redacts_by_field_name_for_plain_str(self) -> None:
        # F3: legacy modules that store credentials as plain str must
        # also be redacted, by field-name match.
        data = {"api_key": "AKIA1234EXAMPLE", "url": "https://x"}
        assert _redact_dict(data) == {"api_key": REDACTED, "url": "https://x"}

    def test_nested_dict_with_secret(self) -> None:
        data = {
            "outer": {
                "inner_secret": SecretStr("abcdefghijklmnop"),
                "auth_token": "ghp_examplevalue",
                "inner_plain": "hello",
            }
        }
        result = _redact_dict(data)
        assert result["outer"]["inner_secret"] == REDACTED
        assert result["outer"]["auth_token"] == REDACTED
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

    def test_redacts_secret_str_field_to_constant(self) -> None:
        settings = ApiSettings(api_key=SecretStr("my-long-api-key-here"))
        dumped = _dump_settings(settings)
        assert dumped["api_key"] == REDACTED
        assert dumped["api_url"] == "https://api.example.com"
        # Defensive: no part of the secret leaks.
        assert "my-l" not in str(dumped)
        assert "here" not in str(dumped)

    def test_redacts_plain_str_credential_by_name(self) -> None:
        # F3: legacy plain-str credentials must also be redacted.
        settings = PlainStrSecretSettings(
            api_key="AKIA1234EXAMPLE",
            auth_token="ghp_examplevalue",
            user_password="hunter2",
            plain_value="visible",
        )
        dumped = _dump_settings(settings)
        assert dumped["api_key"] == REDACTED
        assert dumped["auth_token"] == REDACTED
        assert dumped["user_password"] == REDACTED
        assert dumped["plain_value"] == "visible"
        # Defensive: assert no secret material survives.
        for forbidden in ("AKIA1234EXAMPLE", "ghp_examplevalue", "hunter2"):
            assert forbidden not in str(dumped)

    def test_redacts_dict_field_with_secrets(self) -> None:
        settings = ApiSettings(nested={"token": SecretStr("abcdefghijklmnop"), "label": "prod"})
        dumped = _dump_settings(settings)
        assert dumped["nested"]["token"] == REDACTED
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

        mod = dump["modules"]["api"]
        assert mod["api_key"] == REDACTED
        assert mod["api_url"] == "https://test.example.com"
        # No partial secret survives.
        assert "long" not in str(mod)
        assert "alue" not in str(mod)


# ---------------------------------------------------------------------------
# ConfigResourceAdapter registration — opt-in (F3)
# ---------------------------------------------------------------------------


class TestConfigResourceAdapterOptIn:
    @pytest.mark.unit
    async def test_resource_not_registered_by_default(self) -> None:
        """F3: default deployment must not expose kaos://server/config."""
        from kaos_mcp import create_app

        runtime = KaosRuntime()
        settings = KaosMCPSettings(name="default-test")
        app = create_app(runtime, settings)

        resources = await app.list_resources()
        uris = [str(r.uri) for r in resources]
        assert "kaos://server/config" not in uris

    @pytest.mark.unit
    async def test_resource_registered_when_opted_in(self) -> None:
        from kaos_mcp import create_app

        runtime = KaosRuntime()
        settings = KaosMCPSettings(name="adapter-test", expose_server_config=True)
        app = create_app(runtime, settings)

        resources = await app.list_resources()
        config_resource = [r for r in resources if str(r.uri) == "kaos://server/config"]
        assert len(config_resource) == 1
        assert config_resource[0].name == "server-config"
        assert config_resource[0].mimeType == "application/json"

    @pytest.mark.unit
    async def test_resource_returns_redacted_dump_when_opted_in(self) -> None:
        from kaos_mcp import create_app

        runtime = KaosRuntime()
        runtime.module_settings["api"] = ApiSettings(
            api_key=SecretStr("really-long-secret-key-value-do-not-leak"),
        )
        settings = KaosMCPSettings(name="dump-test", expose_server_config=True)
        app = create_app(runtime, settings)

        contents = list(await app.read_resource("kaos://server/config"))
        assert len(contents) > 0
        import json

        data = json.loads(contents[0].content)
        assert data["server"]["name"] == "dump-test"
        # F3: verify no part of the secret is present anywhere in the dump.
        body = json.dumps(data)
        for forbidden in ("really-long", "do-not-leak"):
            assert forbidden not in body
        assert data["modules"]["api"]["api_key"] == REDACTED
