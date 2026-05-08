"""Tests for ContextBridge config override extraction from MCP _meta."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest
from kaos_core import KaosRuntime
from kaos_core.config.module_settings import ModuleSettings
from pydantic_settings import SettingsConfigDict

from kaos_mcp.adapters.context import ContextBridge
from kaos_mcp.config import KaosMCPSettings


def _make_mock_context(
    *,
    client_id: str = "client-1",
    request_id: str = "req-1",
    meta: Any = None,
) -> MagicMock:
    """Create a mock FastMCPContext with configurable meta."""
    ctx = MagicMock()
    ctx.client_id = client_id
    ctx.request_id = request_id
    ctx.report_progress = AsyncMock()

    # request_context.meta
    request_context = MagicMock()
    request_context.meta = meta
    ctx.request_context = request_context

    # session.list_roots raises ValueError (no session) so roots returns None
    type(ctx).session = PropertyMock(side_effect=ValueError("no session"))

    return ctx


class _TestSettings(ModuleSettings):
    """Minimal settings subclass for testing config override flow."""

    browser_headless: bool = True
    timeout_seconds: float = 30.0

    model_config = SettingsConfigDict(
        env_prefix="KAOS_TEST_BRIDGE_",
        extra="ignore",
    )


class TestConfigOverridesFromMetaDict:
    @pytest.mark.asyncio
    async def test_config_overrides_applied(self) -> None:
        """When meta is a dict with kaos_config, overrides flow to _config."""
        meta = {"kaos_config": {"browser_headless": False, "timeout_seconds": 60.0}}
        ctx = _make_mock_context(meta=meta)
        bridge = ContextBridge(runtime=KaosRuntime(), settings=KaosMCPSettings())

        kaos_context = await bridge.create_kaos_context(ctx)

        assert kaos_context._config["browser_headless"] is False
        assert kaos_context._config["timeout_seconds"] == 60.0


class TestConfigOverridesFromMetaObject:
    @pytest.mark.asyncio
    async def test_config_overrides_from_object(self) -> None:
        """When meta is an object with kaos_config attribute, overrides are extracted."""
        meta_obj = MagicMock()
        meta_obj.progressToken = None
        meta_obj.kaos_config = {"browser_headless": False}
        ctx = _make_mock_context(meta=meta_obj)
        bridge = ContextBridge(runtime=KaosRuntime(), settings=KaosMCPSettings())

        kaos_context = await bridge.create_kaos_context(ctx)

        assert kaos_context._config["browser_headless"] is False


class TestNoConfigWhenMetaMissing:
    @pytest.mark.asyncio
    async def test_no_config_when_meta_is_none(self) -> None:
        """When meta is None, _config should be empty."""
        ctx = _make_mock_context(meta=None)
        bridge = ContextBridge(runtime=KaosRuntime(), settings=KaosMCPSettings())

        kaos_context = await bridge.create_kaos_context(ctx)

        assert kaos_context._config == {}


class TestNoConfigWhenKaosConfigNotDict:
    @pytest.mark.asyncio
    async def test_string_kaos_config_ignored(self) -> None:
        """When kaos_config is a string, it should be ignored."""
        meta = {"kaos_config": "not-a-dict"}
        ctx = _make_mock_context(meta=meta)
        bridge = ContextBridge(runtime=KaosRuntime(), settings=KaosMCPSettings())

        kaos_context = await bridge.create_kaos_context(ctx)

        assert kaos_context._config == {}

    @pytest.mark.asyncio
    async def test_int_kaos_config_ignored(self) -> None:
        """When kaos_config is an int, it should be ignored."""
        meta = {"kaos_config": 42}
        ctx = _make_mock_context(meta=meta)
        bridge = ContextBridge(runtime=KaosRuntime(), settings=KaosMCPSettings())

        kaos_context = await bridge.create_kaos_context(ctx)

        assert kaos_context._config == {}

    @pytest.mark.asyncio
    async def test_none_kaos_config_ignored(self) -> None:
        """When kaos_config is None, _config should be empty."""
        meta = {"kaos_config": None}
        ctx = _make_mock_context(meta=meta)
        bridge = ContextBridge(runtime=KaosRuntime(), settings=KaosMCPSettings())

        kaos_context = await bridge.create_kaos_context(ctx)

        assert kaos_context._config == {}


class TestConfigOverridesFlowToModuleSettings:
    @pytest.mark.asyncio
    async def test_overrides_applied_via_get_module_settings(self) -> None:
        """Config overrides from _meta flow through to ModuleSettings.from_context."""
        meta = {"kaos_config": {"browser_headless": False, "timeout_seconds": 120.0}}
        ctx = _make_mock_context(meta=meta)
        bridge = ContextBridge(runtime=KaosRuntime(), settings=KaosMCPSettings())

        kaos_context = await bridge.create_kaos_context(ctx)

        settings = kaos_context.get_module_settings(_TestSettings)
        assert settings.browser_headless is False
        assert settings.timeout_seconds == 120.0

    @pytest.mark.asyncio
    async def test_defaults_without_overrides(self) -> None:
        """Without config overrides, ModuleSettings returns defaults."""
        ctx = _make_mock_context(meta=None)
        bridge = ContextBridge(runtime=KaosRuntime(), settings=KaosMCPSettings())

        kaos_context = await bridge.create_kaos_context(ctx)

        settings = kaos_context.get_module_settings(_TestSettings)
        assert settings.browser_headless is True
        assert settings.timeout_seconds == 30.0
