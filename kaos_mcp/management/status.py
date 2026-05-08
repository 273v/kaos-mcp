"""Module and server status for the KAOS platform."""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ModuleInfo:
    """Information about a KAOS module."""

    name: str
    import_name: str
    version: str = ""
    installed: bool = False
    tool_count: int = 0
    serve_command: str = ""
    serve_args: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "installed": self.installed,
            "tool_count": self.tool_count,
            "serve_command": self.serve_command,
            "serve_args": self.serve_args,
        }


# Tool counts shown when a package isn't importable in the current venv
# (multi-venv monorepo dev) so ``kaos status`` still reports a useful
# number. When the package IS importable we count via ``register_func``
# instead, so this dict's values are kept in lockstep with the live
# count by ``tests/unit/test_management.py::TestModuleStatus``.
_KNOWN_TOOL_COUNTS: dict[str, int] = {
    "kaos-core": 10,
    "kaos-content": 8,
    "kaos-nlp-core": 17,
    "kaos-graph": 17,
    "kaos-pdf": 7,
    "kaos-web": 42,
    "kaos-office": 17,
    "kaos-tabular": 8,
    "kaos-source": 30,
    "kaos-llm-client": 7,
    "kaos-llm-core": 29,
    "kaos-reference": 6,
}

_MODULES = [
    ("kaos_core", "kaos-core", "register_core_tools", "kaos-core-serve", []),
    ("kaos_content", "kaos-content", "register_content_tools", "kaos-content-serve", []),
    ("kaos_nlp_core", "kaos-nlp-core", "register_nlp_tools", "kaos-nlp-serve", []),
    ("kaos_graph", "kaos-graph", "register_graph_tools", "kaos-graph-serve", []),
    ("kaos_pdf", "kaos-pdf", "register_pdf_tools", "kaos-pdf-serve", []),
    ("kaos_web", "kaos-web", "register_web_tools", "kaos-web-serve", ["--browser", "--crawl"]),
    ("kaos_office", "kaos-office", "register_office_tools", "kaos-office-serve", []),
    ("kaos_tabular", "kaos-tabular", "register_tabular_tools", "kaos-tabular-serve", []),
    ("kaos_source", "kaos-source", "register_source_tools", "kaos-source-serve", []),
    ("kaos_llm_client", "kaos-llm-client", "register_llm_tools", "kaos-llm-serve", []),
    ("kaos_llm_core", "kaos-llm-core", "register_llm_core_tools", "kaos-llm-core-serve", []),
    ("kaos_reference", "kaos-reference", "register_reference_tools", "kaos-reference-serve", []),
]


def get_module_status() -> list[ModuleInfo]:
    """Get status of all KAOS MCP modules."""
    results = []

    for import_name, display_name, register_func, serve_cmd, serve_args in _MODULES:
        info = ModuleInfo(
            name=display_name,
            import_name=import_name,
            serve_command=serve_cmd,
            serve_args=serve_args,
        )
        try:
            mod = importlib.import_module(import_name)
            info.installed = True
            info.version = getattr(mod, "__version__", "?")

            # Count tools by calling register on a temporary runtime
            register_fn = getattr(mod, register_func, None)
            if register_fn is not None:
                from kaos_core import KaosRuntime

                temp_runtime = KaosRuntime()
                info.tool_count = register_fn(temp_runtime)
        except ImportError:
            # Check if package exists on disk (separate venv in monorepo)
            from pathlib import Path

            current = Path(__file__).resolve()
            for parent in current.parents:
                pkg_dir = parent / display_name
                if pkg_dir.is_dir() and (pkg_dir / "pyproject.toml").exists():
                    info.installed = True
                    # Read version from _version.py
                    ver_file = pkg_dir / import_name / "_version.py"
                    if ver_file.exists():
                        for line in ver_file.read_text().splitlines():
                            if line.startswith("__version__"):
                                info.version = line.split("=", 1)[1].strip().strip('"').strip("'")
                    else:
                        info.version = "?"
                    info.tool_count = _KNOWN_TOOL_COUNTS.get(display_name, 0)
                    break

        results.append(info)

    return results


def format_status(modules: list[ModuleInfo]) -> str:
    """Format module status for human display."""
    lines = ["Modules:"]

    total_tools = 0
    server_count = 0
    name_width = max(len(m.name) for m in modules)

    for m in modules:
        if not m.installed:
            lines.append(f"  {m.name:<{name_width}}  not installed")
            continue

        parts = [f"{m.name:<{name_width}}  {m.version:<8}  {m.tool_count:>3} tools"]
        if m.serve_command:
            serve_str = m.serve_command
            if m.serve_args:
                serve_str += " " + " ".join(f"[{a}]" for a in m.serve_args)
            parts.append(f"serve: {serve_str}")
            server_count += 1
        lines.append("  " + "  ".join(parts))
        total_tools += m.tool_count

    lines.append("")
    lines.append(f"Total: {total_tools} MCP tools across {server_count} servers")
    return "\n".join(lines)
