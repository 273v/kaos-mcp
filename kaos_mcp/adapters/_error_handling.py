"""Shared exception-to-ResourceError conversion for MCP adapters."""

from __future__ import annotations

from mcp.server.fastmcp.exceptions import ResourceError as FastMCPResourceError


def resource_error_from_exception(exc: Exception, context: str = "") -> FastMCPResourceError:
    """Convert an exception to FastMCPResourceError, preserving type info.

    Args:
        exc: The caught exception.
        context: Optional context string (e.g., URI or operation name).

    Returns:
        A ``FastMCPResourceError`` whose message includes the original
        exception type name and message.
    """
    error_type = type(exc).__name__
    message = f"{context}: {error_type}: {exc}" if context else f"{error_type}: {exc}"
    return FastMCPResourceError(message)
