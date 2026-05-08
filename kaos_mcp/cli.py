"""Command-line interface for kaos-mcp.

MCP server management and introspection tools.

Every command supports --json for structured output (pipe-friendly).
Without --json, output is human-readable.

Usage:
    kaos-mcp serve [--http] [--host HOST] [--port PORT] [--debug] [--module pdf,web]
    kaos-mcp list-tools [--json]
    kaos-mcp list-resources [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any


def _error(msg: str) -> None:
    """Print error to stderr and exit with non-zero status."""
    print(f"Error: {msg}", file=sys.stderr)
    sys.exit(1)


def _json_out(data: dict[str, Any]) -> None:
    """Write JSON to stdout."""
    print(json.dumps(data, indent=2, default=str))


def _load_modules(runtime: object, modules: str) -> int:
    """Load KAOS modules by name and register their tools.

    Each module name (e.g. "pdf") maps to ``kaos_{name}.register_{name}_tools(runtime)``.
    Returns total number of tools registered.
    """
    import importlib

    total = 0
    for name in modules.split(","):
        name = name.strip()
        if not name:
            continue
        pkg = f"kaos_{name}"
        func_name = f"register_{name}_tools"
        try:
            mod = importlib.import_module(pkg)
        except ModuleNotFoundError:
            print(
                f"Error: Module '{pkg}' not found. Install it first:\n"
                f"  uv pip install {pkg.replace('_', '-')}",
                file=sys.stderr,
            )
            sys.exit(1)
        register_fn = getattr(mod, func_name, None)
        if register_fn is None:
            print(
                f"Error: '{pkg}' has no '{func_name}()' function.\n"
                f"Check that '{pkg}' is a valid KAOS module.",
                file=sys.stderr,
            )
            sys.exit(1)
        count = register_fn(runtime)
        print(f"Loaded {pkg}: {count} tools", file=sys.stderr)
        total += count
    return total


def _cmd_serve(args: argparse.Namespace) -> None:
    """Start the MCP server."""
    from kaos_core import KaosRuntime

    from kaos_mcp.config import KaosMCPSettings
    from kaos_mcp.server import KaosMCPServer

    transport = "streamable-http" if args.http else "stdio"
    settings = KaosMCPSettings(
        transport=transport,
        host=args.host,
        port=args.port,
        debug=args.debug,
    )
    runtime = KaosRuntime.default()

    if args.module:
        _load_modules(runtime, args.module)

    tool_count = len(runtime.tools.search_tools())
    if tool_count == 0:
        print(
            "Warning: No tools registered in the runtime.\n"
            "The MCP server will start with zero tools.\n\n"
            "To load modules, use --module:\n"
            "  kaos-mcp serve --module pdf\n"
            "  kaos-mcp serve --module pdf,web,office\n\n"
            "Or use a module-specific entrypoint:\n"
            "  kaos-pdf-serve          # PDF extraction tools\n"
            "  kaos-web-serve          # Web extraction tools\n\n"
            "Or register tools programmatically before calling serve:\n"
            "  from kaos_pdf import register_pdf_tools\n"
            "  register_pdf_tools(runtime)",
            file=sys.stderr,
        )

    server = KaosMCPServer(runtime=runtime, settings=settings)

    if args.http:
        print(f"Starting MCP server on http://{args.host}:{args.port}", file=sys.stderr)
        server.run_streamable_http()
    else:
        server.run_stdio()


def _cmd_list_tools(args: argparse.Namespace) -> None:
    """List tools available in the MCP server."""
    from kaos_core import KaosRuntime

    runtime = KaosRuntime.default()
    metadata_list = runtime.tools.search_tools()

    if args.json:
        tools = [
            {
                "name": m.name,
                "description": m.description,
                "category": str(m.category),
                "capability": str(m.capability),
                "module": m.module_name,
            }
            for m in metadata_list
        ]
        _json_out({"command": "list-tools", "total": len(tools), "tools": tools})
        return

    if not metadata_list:
        print("No tools registered.")
        return

    name_width = max(len(m.name) for m in metadata_list)
    cat_width = max(len(str(m.category)) for m in metadata_list)
    header = f"{'Name':<{name_width}}  {'Category':<{cat_width}}  Description"
    print(header)
    print("-" * len(header))
    for m in metadata_list:
        desc = (m.description or "")[:60]
        print(f"{m.name:<{name_width}}  {m.category!s:<{cat_width}}  {desc}")


def _cmd_list_resources(args: argparse.Namespace) -> None:
    """List resources available in the MCP server."""
    from kaos_core import KaosRuntime

    runtime = KaosRuntime.default()
    resource_list = runtime.resources.search_resources()

    if args.json:
        resources = [
            {
                "uri": m.uri,
                "name": m.name,
                "description": m.description,
                "resource_type": str(m.resource_type),
                "module": m.provider_module,
            }
            for m in resource_list
        ]
        _json_out({"command": "list-resources", "total": len(resources), "resources": resources})
        return

    if not resource_list:
        print("No resources registered.")
        return

    name_width = max(len(m.name) for m in resource_list)
    type_width = max(len(str(m.resource_type)) for m in resource_list)
    header = f"{'Name':<{name_width}}  {'Type':<{type_width}}  Description"
    print(header)
    print("-" * len(header))
    for m in resource_list:
        desc = (m.description or "")[:60]
        print(f"{m.name:<{name_width}}  {m.resource_type!s:<{type_width}}  {desc}")


def main(argv: list[str] | None = None) -> None:
    """Entry point for kaos-mcp CLI."""
    from kaos_mcp._version import __version__

    parser = argparse.ArgumentParser(
        prog="kaos-mcp",
        description="KAOS MCP server management and introspection",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    # serve
    p_serve = sub.add_parser("serve", help="Start MCP server")
    p_serve.add_argument("--http", action="store_true", help="Use HTTP transport (default: stdio)")
    p_serve.add_argument("--host", default="127.0.0.1", help="HTTP host (default: 127.0.0.1)")
    p_serve.add_argument("--port", type=int, default=8000, help="HTTP port (default: 8000)")
    p_serve.add_argument("--debug", action="store_true", help="Enable debug logging")
    p_serve.add_argument(
        "--module",
        default=None,
        help="Comma-separated KAOS modules to load (e.g. pdf,web,office)",
    )

    # list-tools
    p_list_tools = sub.add_parser("list-tools", help="List available MCP tools")
    p_list_tools.add_argument("--json", action="store_true", help="Structured JSON output")

    # list-resources
    p_list_resources = sub.add_parser("list-resources", help="List available MCP resources")
    p_list_resources.add_argument("--json", action="store_true", help="Structured JSON output")

    args = parser.parse_args(argv)

    handlers = {
        "serve": _cmd_serve,
        "list-tools": _cmd_list_tools,
        "list-resources": _cmd_list_resources,
    }

    try:
        handlers[args.command](args)
    except Exception as exc:
        _error(str(exc))
