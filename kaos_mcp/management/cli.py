"""Unified ``kaos`` CLI for platform management.

Usage:
    kaos doctor [--json]
    kaos status [--json]
    kaos setup claude [--scope project|user|local] [--force]
    kaos setup codex [--force]
    kaos setup gemini [--scope project|user] [--force]
    kaos setup vscode [--force]
    kaos setup cursor [--force]
    kaos serve [--module ...] [--http] [--port PORT]

Project scaffolding (``kaos new``) lives in ``kaos-ui``; install kaos-ui
and use ``kaos-ui new <kind> <name>``.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any


def _json_out(data: dict[str, Any]) -> None:
    print(json.dumps(data, indent=2, default=str))


def _error(msg: str) -> None:
    print(f"Error: {msg}", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------


def _cmd_doctor(args: argparse.Namespace) -> None:
    from kaos_mcp.management.doctor import format_report, run_doctor

    report = run_doctor()
    if args.json:
        _json_out(report.to_dict())
    else:
        print(format_report(report))


def _cmd_status(args: argparse.Namespace) -> None:
    from kaos_mcp.management.status import format_status, get_module_status

    modules = get_module_status()
    if args.json:
        _json_out(
            {
                "command": "status",
                "modules": [m.to_dict() for m in modules],
                "total_tools": sum(m.tool_count for m in modules),
                "server_count": sum(1 for m in modules if m.installed and m.serve_command),
            }
        )
    else:
        print(format_status(modules))


def _cmd_setup(args: argparse.Namespace) -> None:
    from kaos_mcp.management.setup import (
        setup_claude,
        setup_codex,
        setup_cursor,
        setup_gemini,
        setup_vscode,
    )

    target = args.target
    force = getattr(args, "force", False)

    try:
        if target == "env":
            from kaos_mcp.management.env import setup_env

            actions = setup_env(
                python_version=getattr(args, "python_version", "3.14"),
                node_version=getattr(args, "node_version", "24"),
                skip_node=getattr(args, "skip_node", False),
                skip_python=getattr(args, "skip_python", False),
                dry_run=getattr(args, "dry_run", False),
            )
        elif target == "claude":
            actions = setup_claude(scope=getattr(args, "scope", "project"), force=force)
        elif target == "codex":
            actions = setup_codex(force=force)
        elif target == "gemini":
            actions = setup_gemini(scope=getattr(args, "scope", "user"), force=force)
        elif target == "vscode":
            actions = setup_vscode()
        elif target == "cursor":
            actions = setup_cursor()
        else:
            _error(f"Unknown target: {target}. Use: env, claude, codex, gemini, vscode, cursor")
            return
    except RuntimeError as exc:
        _error(str(exc))
        return

    if args.json:
        _json_out({"command": "setup", "target": target, "actions": actions})
    else:
        if actions:
            print(f"Setup {target}:")
            for action in actions:
                print(f"  {action}")
        else:
            print(f"No changes needed for {target}.")


def _cmd_serve(args: argparse.Namespace) -> None:
    """Delegate to kaos-mcp serve with smart defaults."""
    from kaos_mcp.cli import _cmd_serve as mcp_serve

    if not args.module:
        # Auto-detect installed modules
        modules = []
        for name in ("pdf", "web", "office", "tabular", "source"):
            try:
                __import__(f"kaos_{name}")
                modules.append(name)
            except ImportError:
                pass
        args.module = ",".join(modules) if modules else None

    if not args.module:
        _error("No KAOS modules installed. Install at least one: kaos-pdf, kaos-web, etc.")

    mcp_serve(args)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    """Entry point for the unified kaos CLI."""
    parser = argparse.ArgumentParser(
        prog="kaos",
        description="KAOS platform management — health checks, setup, and configuration",
    )
    sub = parser.add_subparsers(dest="command")

    # doctor
    p_doctor = sub.add_parser("doctor", help="Check environment, packages, and credentials")
    p_doctor.add_argument("--json", action="store_true", help="JSON output")

    # status
    p_status = sub.add_parser("status", help="Show module and server status")
    p_status.add_argument("--json", action="store_true", help="JSON output")

    # setup
    p_setup = sub.add_parser(
        "setup",
        help="Set up development environment or configure MCP servers",
    )
    p_setup.add_argument(
        "target",
        choices=["env", "claude", "codex", "gemini", "vscode", "cursor"],
        help="Target: 'env' for toolchain, or agentic environment name",
    )
    p_setup.add_argument(
        "--scope",
        choices=["project", "user", "local"],
        default="project",
        help="Config scope (claude/gemini only, default: project)",
    )
    p_setup.add_argument("--force", action="store_true", help="Force file-based config (skip CLI)")
    p_setup.add_argument("--json", action="store_true", help="JSON output")
    # env-specific options
    p_setup.add_argument("--python-version", default="3.14", help="Python version (default: 3.14)")
    p_setup.add_argument("--node-version", default="24", help="Node.js version (default: 24)")
    p_setup.add_argument("--skip-node", action="store_true", help="Skip Node.js/fnm/pnpm")
    p_setup.add_argument("--skip-python", action="store_true", help="Skip Python/uv")
    p_setup.add_argument("--dry-run", action="store_true", help="Show what would be installed")

    # serve
    p_serve = sub.add_parser("serve", help="Start MCP server with all available modules")
    p_serve.add_argument("--module", help="Comma-separated modules (default: all installed)")
    p_serve.add_argument("--http", action="store_true", help="Use HTTP transport")
    p_serve.add_argument("--host", default="127.0.0.1", help="HTTP host")
    p_serve.add_argument("--port", type=int, default=8000, help="HTTP port")
    p_serve.add_argument("--debug", action="store_true", help="Debug logging")

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    handlers = {
        "doctor": _cmd_doctor,
        "status": _cmd_status,
        "setup": _cmd_setup,
        "serve": _cmd_serve,
    }

    handlers[args.command](args)
