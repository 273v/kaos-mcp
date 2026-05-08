"""Auto-configure MCP servers in agentic environments.

Non-destructively adds KAOS MCP server entries to Claude Code, Codex, Gemini,
VS Code, and Cursor config files. Prefers using the tool's native CLI (e.g.
``claude mcp add``) when available, falling back to direct file editing.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any


def _find_kaos_dir() -> Path:
    """Find the kaos-modules root directory.

    Walks up from this file to find the directory containing kaos-core/.
    """
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "kaos-core").is_dir() and (parent / "kaos-mcp").is_dir():
            return parent
    # Fallback: check cwd
    cwd = Path.cwd()
    if (cwd / "kaos-core").is_dir():
        return cwd
    msg = (
        "Could not find kaos-modules root directory. "
        "Run this command from the kaos-modules directory."
    )
    raise RuntimeError(msg)


def _server_entries(kaos_dir: Path) -> dict[str, dict[str, Any]]:
    """Generate MCP server entries for all KAOS modules."""
    d = str(kaos_dir)
    govinfo_key = os.environ.get("GOVINFO_API_KEY", "")
    env_ref = {"GOVINFO_API_KEY": govinfo_key} if govinfo_key else {}

    return {
        "kaos-pdf": {
            "command": "uv",
            "args": [
                "run",
                "--directory",
                f"{d}/kaos-pdf",
                "--extra",
                "mcp",
                "kaos-pdf-serve",
            ],
        },
        "kaos-web": {
            "command": "uv",
            "args": [
                "run",
                "--directory",
                f"{d}/kaos-web",
                "--extra",
                "mcp",
                "--extra",
                "browser",
                "kaos-web-serve",
                "--browser",
                "--crawl",
            ],
        },
        "kaos-office": {
            "command": "uv",
            "args": [
                "run",
                "--directory",
                f"{d}/kaos-office",
                "--extra",
                "mcp",
                "kaos-office-serve",
            ],
        },
        "kaos-tabular": {
            "command": "uv",
            "args": [
                "run",
                "--directory",
                f"{d}/kaos-tabular",
                "--extra",
                "mcp",
                "kaos-tabular-serve",
            ],
        },
        "kaos-source": {
            "command": "uv",
            "args": [
                "run",
                "--directory",
                f"{d}/kaos-source",
                "--extra",
                "mcp",
                "--extra",
                "pacer",
                "kaos-source-serve",
            ],
            **({"env": env_ref} if env_ref else {}),
        },
    }


# ---------------------------------------------------------------------------
# Claude Code
# ---------------------------------------------------------------------------


def setup_claude(
    kaos_dir: Path | None = None,
    scope: str = "project",
    force: bool = False,
) -> list[str]:
    """Configure KAOS MCP servers for Claude Code.

    Prefers ``claude mcp add`` CLI when available. Falls back to writing .mcp.json.

    Returns list of actions taken.
    """
    kaos_dir = kaos_dir or _find_kaos_dir()
    entries = _server_entries(kaos_dir)
    actions: list[str] = []

    # Try CLI first
    if shutil.which("claude") and not force:
        for name, entry in entries.items():
            cmd = ["claude", "mcp", "add", "--transport", "stdio", "-s", scope]
            for k, v in entry.get("env", {}).items():
                cmd.extend(["-e", f"{k}={v}"])
            cmd.extend([name, "--"])
            cmd.append(entry["command"])
            cmd.extend(entry["args"])
            try:
                subprocess.run(cmd, capture_output=True, timeout=15, check=False)
                actions.append(f"Added {name} via claude mcp add (scope: {scope})")
            except (subprocess.TimeoutExpired, FileNotFoundError):
                actions.append(f"Failed to add {name} via CLI, falling back to file")
                _write_mcp_json(kaos_dir, entries, actions)
                return actions
        return actions

    # Fallback: write .mcp.json
    _write_mcp_json(kaos_dir, entries, actions)
    return actions


def _write_mcp_json(
    kaos_dir: Path,
    entries: dict[str, dict[str, Any]],
    actions: list[str],
) -> None:
    """Write or merge .mcp.json file."""
    mcp_path = Path.cwd() / ".mcp.json"
    existing: dict[str, Any] = {}

    if mcp_path.exists():
        with contextlib.suppress(json.JSONDecodeError):
            existing = json.loads(mcp_path.read_text())

    servers = existing.setdefault("mcpServers", {})
    for name, entry in entries.items():
        servers[name] = entry
        actions.append(f"Added {name} to .mcp.json")

    mcp_path.write_text(json.dumps(existing, indent=2) + "\n")


# ---------------------------------------------------------------------------
# Codex CLI
# ---------------------------------------------------------------------------


def setup_codex(
    kaos_dir: Path | None = None,
    force: bool = False,
) -> list[str]:
    """Configure KAOS MCP servers for Codex CLI.

    Prefers ``codex mcp add`` CLI. Falls back to editing ~/.codex/config.toml.

    Returns list of actions taken.
    """
    kaos_dir = kaos_dir or _find_kaos_dir()
    entries = _server_entries(kaos_dir)
    actions: list[str] = []

    if shutil.which("codex") and not force:
        for name, entry in entries.items():
            cmd = ["codex", "mcp", "add", name]
            for k, v in entry.get("env", {}).items():
                cmd.extend(["--env", f"{k}={v}"])
            cmd.append("--")
            cmd.append(entry["command"])
            cmd.extend(entry["args"])
            try:
                subprocess.run(cmd, capture_output=True, timeout=15, check=False)
                actions.append(f"Added {name} via codex mcp add")
            except (subprocess.TimeoutExpired, FileNotFoundError):
                actions.append(f"Failed to add {name} via CLI")
        return actions

    # Fallback: write to config.toml
    _write_codex_toml(kaos_dir, entries, actions)
    return actions


def _write_codex_toml(
    kaos_dir: Path,
    entries: dict[str, dict[str, Any]],
    actions: list[str],
) -> None:
    """Append KAOS server entries to ~/.codex/config.toml."""
    config_dir = Path.home() / ".codex"
    config_dir.mkdir(exist_ok=True)
    config_path = config_dir / "config.toml"

    existing = config_path.read_text() if config_path.exists() else ""
    lines: list[str] = []

    for name, entry in entries.items():
        toml_name = name.replace("-", "_")
        section = f"[mcp_servers.{toml_name}]"
        if section in existing:
            actions.append(f"Skipped {name} (already in config.toml)")
            continue
        lines.append(f"\n{section}")
        lines.append(f'command = "{entry["command"]}"')
        args_str = ", ".join(f'"{a}"' for a in entry["args"])
        lines.append(f"args = [{args_str}]")
        for k, v in entry.get("env", {}).items():
            lines.append(f"\n[mcp_servers.{toml_name}.env]")
            lines.append(f'{k} = "{v}"')
        actions.append(f"Added {name} to ~/.codex/config.toml")

    if lines:
        with config_path.open("a") as f:
            f.write("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Gemini CLI
# ---------------------------------------------------------------------------


def setup_gemini(
    kaos_dir: Path | None = None,
    scope: str = "user",
    force: bool = False,
) -> list[str]:
    """Configure KAOS MCP servers for Gemini CLI.

    Prefers ``gemini mcp add``. Falls back to editing ~/.gemini/settings.json.
    """
    kaos_dir = kaos_dir or _find_kaos_dir()
    entries = _server_entries(kaos_dir)
    actions: list[str] = []

    if shutil.which("gemini") and not force:
        for name, entry in entries.items():
            cmd = ["gemini", "mcp", "add", "-s", scope, "-t", "stdio"]
            for k, v in entry.get("env", {}).items():
                cmd.extend(["-e", f"{k}={v}"])
            cmd.extend([name, entry["command"]])
            cmd.extend(entry["args"])
            try:
                subprocess.run(cmd, capture_output=True, timeout=15, check=False)
                actions.append(f"Added {name} via gemini mcp add (scope: {scope})")
            except (subprocess.TimeoutExpired, FileNotFoundError):
                actions.append(f"Failed to add {name} via CLI")
        return actions

    # Fallback: write settings.json
    _write_gemini_json(kaos_dir, entries, actions)
    return actions


def _write_gemini_json(
    kaos_dir: Path,
    entries: dict[str, dict[str, Any]],
    actions: list[str],
) -> None:
    """Write or merge ~/.gemini/settings.json."""
    config_dir = Path.home() / ".gemini"
    config_dir.mkdir(exist_ok=True)
    config_path = config_dir / "settings.json"

    existing: dict[str, Any] = {}
    if config_path.exists():
        with contextlib.suppress(json.JSONDecodeError):
            existing = json.loads(config_path.read_text())

    servers = existing.setdefault("mcpServers", {})
    for name, entry in entries.items():
        servers[name] = entry
        actions.append(f"Added {name} to ~/.gemini/settings.json")

    config_path.write_text(json.dumps(existing, indent=2) + "\n")


# ---------------------------------------------------------------------------
# VS Code / Cursor (direct file write — no CLI available)
# ---------------------------------------------------------------------------


def setup_vscode(kaos_dir: Path | None = None) -> list[str]:
    """Configure KAOS MCP servers for VS Code (.vscode/mcp.json)."""
    kaos_dir = kaos_dir or _find_kaos_dir()
    entries = _server_entries(kaos_dir)
    actions: list[str] = []

    vscode_dir = Path.cwd() / ".vscode"
    vscode_dir.mkdir(exist_ok=True)
    config_path = vscode_dir / "mcp.json"

    existing: dict[str, Any] = {}
    if config_path.exists():
        with contextlib.suppress(json.JSONDecodeError):
            existing = json.loads(config_path.read_text())

    # VS Code uses "servers" key (not "mcpServers")
    servers = existing.setdefault("servers", {})
    for name, entry in entries.items():
        servers[name] = {"type": "stdio", **entry}
        actions.append(f"Added {name} to .vscode/mcp.json")

    config_path.write_text(json.dumps(existing, indent=2) + "\n")
    return actions


def setup_cursor(kaos_dir: Path | None = None) -> list[str]:
    """Configure KAOS MCP servers for Cursor (.cursor/mcp.json)."""
    kaos_dir = kaos_dir or _find_kaos_dir()
    entries = _server_entries(kaos_dir)
    actions: list[str] = []

    cursor_dir = Path.cwd() / ".cursor"
    cursor_dir.mkdir(exist_ok=True)
    config_path = cursor_dir / "mcp.json"

    existing: dict[str, Any] = {}
    if config_path.exists():
        with contextlib.suppress(json.JSONDecodeError):
            existing = json.loads(config_path.read_text())

    servers = existing.setdefault("mcpServers", {})
    for name, entry in entries.items():
        servers[name] = entry
        actions.append(f"Added {name} to .cursor/mcp.json")

    config_path.write_text(json.dumps(existing, indent=2) + "\n")
    return actions
