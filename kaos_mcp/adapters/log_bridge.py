"""Bridge Python logging to MCP client log notifications.

During MCP tool execution, installs a ``logging.Handler`` on the ``kaos``
root logger that forwards log records to the MCP client via
``session.send_log_message()``.  The handler is scoped to the tool execution
context and removed afterwards.

Usage in ToolAdapter::

    async with bridge_logs_to_mcp(fastmcp_context):
        result = await tool.execute(inputs, context=kaos_context)

The module also provides :func:`register_set_logging_level` to wire the
MCP ``logging/setLevel`` request so clients can dynamically adjust the
minimum log level forwarded during tool execution.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from kaos_core.logging import get_logger
from mcp.server.fastmcp import Context as FastMCPContext

# ---------------------------------------------------------------------------
# Level mapping
# ---------------------------------------------------------------------------

_MCP_LEVEL_TO_PYTHON: dict[str, int] = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "notice": logging.INFO,  # Python has no NOTICE; map to INFO
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
    "alert": logging.CRITICAL,  # Python has no ALERT; map to CRITICAL
    "emergency": logging.CRITICAL,  # Python has no EMERGENCY; map to CRITICAL
}


def _map_level(levelno: int) -> str:
    """Map Python log level number to MCP log level string."""
    if levelno >= logging.CRITICAL:
        return "critical"
    if levelno >= logging.ERROR:
        return "error"
    if levelno >= logging.WARNING:
        return "warning"
    if levelno >= logging.INFO:
        return "info"
    return "debug"


def mcp_level_to_python(level: str) -> int:
    """Map an MCP log level string to a Python logging level.

    Returns ``logging.INFO`` for unrecognised levels.
    """
    return _MCP_LEVEL_TO_PYTHON.get(level.lower(), logging.INFO)


# ---------------------------------------------------------------------------
# Dynamic log level state
# ---------------------------------------------------------------------------

_current_log_level: int = logging.INFO


def get_log_level() -> int:
    """Return the current MCP log forwarding level."""
    return _current_log_level


def set_log_level(level: int) -> None:
    """Set the MCP log forwarding level (Python int)."""
    global _current_log_level
    _current_log_level = level


# ---------------------------------------------------------------------------
# MCP set_logging_level handler registration
# ---------------------------------------------------------------------------


def register_set_logging_level(app: Any) -> None:
    """Register the MCP ``logging/setLevel`` handler on *app*.

    The handler updates the module-level log forwarding level so that
    subsequent :func:`bridge_logs_to_mcp` calls use the new minimum.

    Args:
        app: A ``FastMCP`` instance.
    """
    server = app._mcp_server

    @server.set_logging_level()
    async def handle_set_level(level: str) -> None:
        set_log_level(mcp_level_to_python(level))


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


class McpLogHandler(logging.Handler):
    """Forwards Python log records to an MCP client session.

    Log records are sent as ``notifications/message`` via
    ``session.send_log_message()``.  The async send is scheduled on the
    event loop as a fire-and-forget task.
    """

    def __init__(
        self,
        context: FastMCPContext,
        *,
        level: int = logging.INFO,
    ) -> None:
        super().__init__(level=level)
        self._context = context
        self._loop: asyncio.AbstractEventLoop | None = None

    def emit(self, record: logging.LogRecord) -> None:
        """Schedule an async send of the log record to the MCP client."""
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        mcp_level = _map_level(record.levelno)
        message = self.format(record) if self.formatter else record.getMessage()
        logger_name = record.name

        # Fire-and-forget: schedule the coroutine on the event loop
        loop.call_soon_threadsafe(self._schedule_send, loop, mcp_level, message, logger_name)

    def _schedule_send(
        self,
        loop: asyncio.AbstractEventLoop,
        level: str,
        message: str,
        logger_name: str,
    ) -> None:
        """Create a task to send the log message (called from call_soon_threadsafe)."""
        with contextlib.suppress(RuntimeError):
            loop.create_task(self._send(level, message, logger_name))

    async def _send(self, level: str, message: str, logger_name: str) -> None:
        """Actually send the log notification to the MCP session."""
        try:
            session = self._context.session
        except (ValueError, AttributeError):
            return
        with contextlib.suppress(Exception):
            await session.send_log_message(
                level=level,
                data=message,
                logger=logger_name,
                related_request_id=self._context.request_id,
            )


# ---------------------------------------------------------------------------
# Bridge context manager
# ---------------------------------------------------------------------------


@asynccontextmanager
async def bridge_logs_to_mcp(
    context: FastMCPContext,
    *,
    level: int | None = None,
) -> AsyncIterator[McpLogHandler]:
    """Install MCP log forwarding on the ``kaos`` root logger for this scope.

    All log records at *level* or above emitted to the ``kaos.*`` logger
    hierarchy will be forwarded to the MCP client as log notifications.

    When *level* is ``None`` (the default), the dynamic level set by
    :func:`set_log_level` (or the MCP ``logging/setLevel`` handler) is used.

    Args:
        context: The ``FastMCPContext`` for the current tool execution.
        level: Minimum Python log level to forward.  ``None`` uses the
            dynamic level (default ``INFO``).

    Yields:
        The installed ``McpLogHandler`` (mainly useful for testing).
    """
    effective_level = level if level is not None else get_log_level()
    handler = McpLogHandler(context, level=effective_level)
    try:
        handler._loop = asyncio.get_running_loop()
    except RuntimeError:
        handler._loop = None

    kaos_logger = get_logger("kaos")
    kaos_logger.addHandler(handler)
    try:
        yield handler
    finally:
        kaos_logger.removeHandler(handler)
