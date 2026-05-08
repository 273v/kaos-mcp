"""Tests for MCP log bridging."""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from kaos_mcp.adapters.log_bridge import (
    McpLogHandler,
    _map_level,
    bridge_logs_to_mcp,
    get_log_level,
    mcp_level_to_python,
    register_set_logging_level,
    set_log_level,
)


class TestMapLevel:
    def test_debug(self) -> None:
        assert _map_level(logging.DEBUG) == "debug"

    def test_info(self) -> None:
        assert _map_level(logging.INFO) == "info"

    def test_warning(self) -> None:
        assert _map_level(logging.WARNING) == "warning"

    def test_error(self) -> None:
        assert _map_level(logging.ERROR) == "error"

    def test_critical(self) -> None:
        assert _map_level(logging.CRITICAL) == "critical"

    def test_between_levels(self) -> None:
        # Level between WARNING and ERROR maps to warning
        assert _map_level(35) == "warning"


def _make_mock_context(request_id: str = "req-123") -> MagicMock:
    """Create a mock FastMCPContext with a mock session."""
    ctx = MagicMock()
    ctx.request_id = request_id
    ctx.session.send_log_message = AsyncMock()
    return ctx


class TestMcpLogHandler:
    def test_handler_creation(self) -> None:
        ctx = _make_mock_context()
        handler = McpLogHandler(ctx)
        assert handler.level == logging.INFO

    def test_handler_custom_level(self) -> None:
        ctx = _make_mock_context()
        handler = McpLogHandler(ctx, level=logging.WARNING)
        assert handler.level == logging.WARNING


class TestBridgeLogsToMcp:
    @pytest.mark.asyncio
    async def test_handler_installed_and_removed(self) -> None:
        """Handler is added to kaos logger during scope and removed after."""
        ctx = _make_mock_context()
        kaos_logger = logging.getLogger("kaos")
        initial_count = len(kaos_logger.handlers)

        async with bridge_logs_to_mcp(ctx) as handler:
            assert handler in kaos_logger.handlers
            assert len(kaos_logger.handlers) == initial_count + 1

        assert handler not in kaos_logger.handlers
        assert len(kaos_logger.handlers) == initial_count

    @pytest.mark.asyncio
    async def test_log_record_reaches_session(self) -> None:
        """Log records emitted during bridge scope are sent to MCP session."""
        ctx = _make_mock_context()

        async with bridge_logs_to_mcp(ctx):
            logger = logging.getLogger("kaos.test.bridge")
            logger.setLevel(logging.DEBUG)
            logger.info("Test log message")

            # Give the fire-and-forget task a chance to run
            await asyncio.sleep(0.05)

        ctx.session.send_log_message.assert_called()
        call_args = ctx.session.send_log_message.call_args
        assert call_args.kwargs["level"] == "info" or call_args[1]["level"] == "info"

    @pytest.mark.asyncio
    async def test_below_level_not_forwarded(self) -> None:
        """Records below the handler level are not forwarded."""
        ctx = _make_mock_context()

        async with bridge_logs_to_mcp(ctx, level=logging.WARNING):
            logger = logging.getLogger("kaos.test.bridge.level")
            logger.setLevel(logging.DEBUG)
            logger.debug("Should not be forwarded")

            await asyncio.sleep(0.05)

        ctx.session.send_log_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_handler_cleaned_up_on_error(self) -> None:
        """Handler is removed even if the scope raises an exception."""
        ctx = _make_mock_context()
        kaos_logger = logging.getLogger("kaos")
        initial_count = len(kaos_logger.handlers)

        with pytest.raises(RuntimeError, match="test error"):
            async with bridge_logs_to_mcp(ctx):
                raise RuntimeError("test error")

        assert len(kaos_logger.handlers) == initial_count

    @pytest.mark.asyncio
    async def test_session_error_does_not_propagate(self) -> None:
        """Errors in session.send_log_message are swallowed."""
        ctx = _make_mock_context()
        ctx.session.send_log_message = AsyncMock(side_effect=RuntimeError("send failed"))

        async with bridge_logs_to_mcp(ctx):
            logger = logging.getLogger("kaos.test.bridge.error")
            logger.setLevel(logging.DEBUG)
            logger.error("This should not crash")

            await asyncio.sleep(0.05)

        # Test passes if no exception propagated

    @pytest.mark.asyncio
    async def test_logger_name_preserved(self) -> None:
        """The logger name is passed through to MCP."""
        ctx = _make_mock_context()

        async with bridge_logs_to_mcp(ctx):
            logger = logging.getLogger("kaos.web.extract")
            logger.setLevel(logging.DEBUG)
            logger.warning("extraction warning")

            await asyncio.sleep(0.05)

        ctx.session.send_log_message.assert_called()
        call_kwargs = ctx.session.send_log_message.call_args.kwargs
        assert call_kwargs.get("logger") == "kaos.web.extract"


class TestMcpLevelToPython:
    def test_debug(self) -> None:
        assert mcp_level_to_python("debug") == logging.DEBUG

    def test_info(self) -> None:
        assert mcp_level_to_python("info") == logging.INFO

    def test_notice_maps_to_info(self) -> None:
        assert mcp_level_to_python("notice") == logging.INFO

    def test_warning(self) -> None:
        assert mcp_level_to_python("warning") == logging.WARNING

    def test_error(self) -> None:
        assert mcp_level_to_python("error") == logging.ERROR

    def test_critical(self) -> None:
        assert mcp_level_to_python("critical") == logging.CRITICAL

    def test_alert_maps_to_critical(self) -> None:
        assert mcp_level_to_python("alert") == logging.CRITICAL

    def test_emergency_maps_to_critical(self) -> None:
        assert mcp_level_to_python("emergency") == logging.CRITICAL

    def test_unknown_defaults_to_info(self) -> None:
        assert mcp_level_to_python("custom") == logging.INFO

    def test_case_insensitive(self) -> None:
        assert mcp_level_to_python("WARNING") == logging.WARNING


class TestDynamicLogLevel:
    def test_default_level_is_info(self) -> None:
        set_log_level(logging.INFO)  # reset to known state
        assert get_log_level() == logging.INFO

    def test_set_and_get(self) -> None:
        original = get_log_level()
        try:
            set_log_level(logging.DEBUG)
            assert get_log_level() == logging.DEBUG
            set_log_level(logging.ERROR)
            assert get_log_level() == logging.ERROR
        finally:
            set_log_level(original)

    @pytest.mark.asyncio
    async def test_bridge_uses_dynamic_level(self) -> None:
        """bridge_logs_to_mcp() uses the dynamic level when no explicit level given."""
        original = get_log_level()
        try:
            set_log_level(logging.WARNING)
            ctx = _make_mock_context()

            async with bridge_logs_to_mcp(ctx) as handler:
                assert handler.level == logging.WARNING
        finally:
            set_log_level(original)

    @pytest.mark.asyncio
    async def test_bridge_explicit_level_overrides_dynamic(self) -> None:
        """An explicit level= param overrides the dynamic level."""
        original = get_log_level()
        try:
            set_log_level(logging.WARNING)
            ctx = _make_mock_context()

            async with bridge_logs_to_mcp(ctx, level=logging.DEBUG) as handler:
                assert handler.level == logging.DEBUG
        finally:
            set_log_level(original)


class TestRegisterSetLoggingLevel:
    def test_registers_handler(self) -> None:
        """register_set_logging_level installs a handler on the low-level server."""
        from mcp.server.fastmcp import FastMCP
        from mcp.types import SetLevelRequest

        app = FastMCP("test-log-level")
        register_set_logging_level(app)
        assert SetLevelRequest in app._mcp_server.request_handlers

    @pytest.mark.asyncio
    async def test_handler_updates_log_level(self) -> None:
        """The registered handler updates the dynamic log level."""
        from mcp.server.fastmcp import FastMCP
        from mcp.types import SetLevelRequest, SetLevelRequestParams

        original = get_log_level()
        try:
            set_log_level(logging.INFO)
            app = FastMCP("test-log-level")
            register_set_logging_level(app)

            # Simulate the MCP request
            handler = app._mcp_server.request_handlers[SetLevelRequest]
            request = SetLevelRequest(
                method="logging/setLevel",
                params=SetLevelRequestParams(level="debug"),
            )
            await handler(request)
            assert get_log_level() == logging.DEBUG
        finally:
            set_log_level(original)
