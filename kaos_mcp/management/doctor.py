"""Health checks for the KAOS platform.

Checks packages, dependencies, credentials, and agentic environments.
"""

from __future__ import annotations

import importlib
import os
import platform
import shutil
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kaos_mcp.management.env import MIN_HARDENED_PNPM_VERSION, _version_lt


@dataclass
class Check:
    """A single health check result."""

    name: str
    status: str  # "ok", "warn", "fail"
    message: str
    category: str = "general"
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "status": self.status,
            "message": self.message,
            "category": self.category,
        }
        if self.detail:
            d["detail"] = self.detail
        return d


@dataclass
class DoctorReport:
    """Full health check report."""

    checks: list[Check] = field(default_factory=list)

    @property
    def ok_count(self) -> int:
        return sum(1 for c in self.checks if c.status == "ok")

    @property
    def warn_count(self) -> int:
        return sum(1 for c in self.checks if c.status == "warn")

    @property
    def fail_count(self) -> int:
        return sum(1 for c in self.checks if c.status == "fail")

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": "doctor",
            "ok": self.ok_count,
            "warn": self.warn_count,
            "fail": self.fail_count,
            "total": len(self.checks),
            "checks": [c.to_dict() for c in self.checks],
        }


# ---------------------------------------------------------------------------
# Known packages and their attributes
# ---------------------------------------------------------------------------

# (import_name, display_name, has_serve, optional_extras)
_CORE_PACKAGES = [
    ("kaos_core", "kaos-core", False, []),
    ("kaos_content", "kaos-content", False, [("kaos_nlp_core", "nlp (kaos-nlp-core)")]),
    ("kaos_mcp", "kaos-mcp", False, []),
]

_SERVE_PACKAGES = [
    ("kaos_pdf", "kaos-pdf", True, []),
    ("kaos_web", "kaos-web", True, [("playwright", "browser (playwright)")]),
    ("kaos_office", "kaos-office", True, []),
    ("kaos_tabular", "kaos-tabular", True, [("duckdb", "duckdb"), ("polars", "polars")]),
    ("kaos_source", "kaos-source", True, [("lxml", "pacer (lxml)")]),
]

_OPTIONAL_PACKAGES = [
    ("kaos_graph", "kaos-graph", False, []),
    ("kaos_llm_client", "kaos-llm-client", False, []),
    ("kaos_llm_core", "kaos-llm-core", False, []),
    ("kaos_ml_core", "kaos-ml-core", False, []),
    ("kaos_nlp_core", "kaos-nlp-core", False, []),
    ("kaos_nlp_transformers", "kaos-nlp-transformers", False, []),
    ("kaos_reference", "kaos-reference", False, []),
]

# Known credential env vars: (env_var, display_name, required)
_CREDENTIALS = [
    ("GOVINFO_API_KEY", "GovInfo API key", False),
    ("KAOS_SOURCE_GOVINFO_API_KEY", "GovInfo API key (new)", False),
    ("SERPAPI_API_KEY", "SerpAPI key", False),
    ("KAOS_WEB_SERPAPI_API_KEY", "SerpAPI key (new)", False),
    ("EXA_API_KEY", "Exa API key", False),
    ("KAOS_WEB_EXA_API_KEY", "Exa API key (new)", False),
    ("BRAVE_API_KEY", "Brave Search key", False),
    ("KAOS_WEB_BRAVE_API_KEY", "Brave Search key (new)", False),
]

# Agentic CLI tools: (binary_name, display_name, config_check_func_name)
_AGENTIC_TOOLS = [
    ("claude", "Claude Code"),
    ("codex", "Codex CLI"),
    ("gemini", "Gemini CLI"),
]


def _find_package_dir(display_name: str) -> Path | None:
    """Find a KAOS package directory on disk (monorepo layout).

    Searches: KAOS_MODULES_DIR env var, then cwd ancestors, then __file__ ancestors.
    """
    search_roots: list[Path] = []
    # Explicit env var (for uvx / isolated installs)
    env_dir = os.environ.get("KAOS_MODULES_DIR")
    if env_dir:
        search_roots.append(Path(env_dir).resolve())
    # cwd and its parents (covers `cd kaos-modules && uvx ...`)
    search_roots.append(Path.cwd().resolve())
    for parent in Path.cwd().resolve().parents:
        search_roots.append(parent)
    # __file__ parents (covers in-repo `uv run`)
    current = Path(__file__).resolve()
    for parent in current.parents:
        search_roots.append(parent)

    for root in search_roots:
        pkg_path = root / display_name
        if pkg_path.is_dir() and (pkg_path / "pyproject.toml").exists():
            return pkg_path
    return None


def _read_version_file(path: Path) -> str:
    """Read __version__ from a _version.py file."""
    if not path.exists():
        return "?"
    try:
        content = path.read_text()
        for line in content.splitlines():
            if line.startswith("__version__"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except (OSError, UnicodeDecodeError):
        pass
    return "?"


def _cargo_to_pep440(cargo_version: str) -> str:
    """Map a Cargo SemVer version to its PEP 440 form.

    Cargo's pre-release suffix (``-alpha.N``, ``-beta.N``, ``-rc.N``) is
    spelled differently from PEP 440 (``aN``, ``bN``, ``rcN``). Rust
    crates whose Python wheels are built by maturin go through this
    normalization at build time; we replicate it here so the doctor
    reports the same string ``pip show`` would.
    """
    base, _, suffix = cargo_version.partition("-")
    if not suffix:
        return cargo_version
    suffix_map = {"alpha": "a", "beta": "b", "rc": "rc"}
    label, _, num = suffix.partition(".")
    short = suffix_map.get(label)
    if short is None or not num.isdigit():
        return cargo_version
    return f"{base}{short}{num}"


def _read_package_version(pkg_dir: Path, import_name: str) -> str:
    """Read a package version from common monorepo layouts.

    Supports:
    - hatch packages with ``<import_name>/_version.py``
    - maturin packages with ``python/<import_name>/_version.py``
    - static ``project.version`` in ``pyproject.toml``
    - Rust+PyO3 packages whose version lives in ``Cargo.toml``
      ``[package].version`` (maturin reads it from there at build time)
    """
    candidates = [
        pkg_dir / import_name / "_version.py",
        pkg_dir / "python" / import_name / "_version.py",
    ]
    for candidate in candidates:
        version = _read_version_file(candidate)
        if version != "?":
            return version

    pyproject = pkg_dir / "pyproject.toml"
    if pyproject.exists():
        try:
            project = tomllib.loads(pyproject.read_text()).get("project", {})
            version = project.get("version")
            if isinstance(version, str) and version:
                return version
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
            pass

    cargo_toml = pkg_dir / "Cargo.toml"
    if cargo_toml.exists():
        try:
            package = tomllib.loads(cargo_toml.read_text()).get("package", {})
            cargo_version = package.get("version")
            if isinstance(cargo_version, str) and cargo_version:
                return _cargo_to_pep440(cargo_version)
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
            pass

    return "?"


def _check_python(report: DoctorReport) -> None:
    """Check Python version."""
    ver = platform.python_version()
    major, minor = sys.version_info[:2]
    if major >= 3 and minor >= 13:
        report.checks.append(Check("python", "ok", f"Python {ver}", "environment"))
    else:
        report.checks.append(Check("python", "fail", f"Python {ver} (need 3.13+)", "environment"))


def _check_uv(report: DoctorReport) -> None:
    """Check uv availability."""
    uv = shutil.which("uv")
    if uv:
        version = _run_version_cmd("uv", "--version")
        report.checks.append(Check("uv", "ok", f"uv {version}", "environment"))
    else:
        report.checks.append(
            Check("uv", "fail", "uv not found (run: kaos setup env)", "environment")
        )


def _check_fnm(report: DoctorReport) -> None:
    """Check fnm (Fast Node Manager)."""
    fnm = shutil.which("fnm")
    if fnm:
        version = _run_version_cmd("fnm", "--version")
        report.checks.append(Check("fnm", "ok", f"fnm {version}", "environment"))
    else:
        report.checks.append(
            Check("fnm", "warn", "fnm not found (run: kaos setup env)", "environment")
        )


def _check_node(report: DoctorReport) -> None:
    """Check Node.js."""
    node = shutil.which("node")
    if node:
        version = _run_version_cmd("node", "--version")
        report.checks.append(Check("node", "ok", f"Node.js {version}", "environment"))
    else:
        report.checks.append(
            Check("node", "warn", "Node.js not found (run: kaos setup env)", "environment")
        )


def _check_pnpm(report: DoctorReport) -> None:
    """Check pnpm."""
    pnpm = shutil.which("pnpm")
    if pnpm:
        version = _run_version_cmd("pnpm", "--version")
        if _version_lt(version, MIN_HARDENED_PNPM_VERSION):
            report.checks.append(
                Check(
                    "pnpm",
                    "warn",
                    (
                        f"pnpm {version} (need >= {MIN_HARDENED_PNPM_VERSION} for "
                        "KAOS Node supply-chain hardening; run: kaos setup env)"
                    ),
                    "environment",
                )
            )
        else:
            report.checks.append(Check("pnpm", "ok", f"pnpm {version}", "environment"))
    else:
        report.checks.append(
            Check("pnpm", "warn", "pnpm not found (run: kaos setup env)", "environment")
        )


def _check_docker(report: DoctorReport) -> None:
    """Check Docker and docker compose."""
    docker = shutil.which("docker")
    if docker:
        version = _run_version_cmd("docker", "--version")
        report.checks.append(Check("docker", "ok", f"Docker {version}", "environment"))
        # Check docker compose
        compose_version = _run_version_cmd("docker", "compose", "version")
        if compose_version:
            report.checks.append(
                Check("docker-compose", "ok", f"docker compose {compose_version}", "environment")
            )
    else:
        report.checks.append(
            Check(
                "docker", "warn", "Docker not installed (optional, for deployment)", "environment"
            )
        )


def _check_git(report: DoctorReport) -> None:
    """Check git."""
    git = shutil.which("git")
    if git:
        version = _run_version_cmd("git", "--version")
        report.checks.append(Check("git", "ok", f"git {version}", "environment"))
    else:
        report.checks.append(Check("git", "warn", "git not found", "environment"))


def _run_version_cmd(*cmd: str) -> str:
    """Run a command and return its output, stripped."""
    import subprocess

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return result.stdout.strip() or result.stderr.strip()
    except (OSError, subprocess.SubprocessError):
        return "?"


def _check_package(
    report: DoctorReport,
    import_name: str,
    display_name: str,
    has_serve: bool,
    extras: list[tuple[str, str]],
) -> None:
    """Check a single package."""
    try:
        mod = importlib.import_module(import_name)
        version = getattr(mod, "__version__", "?")
        parts = [f"{display_name} {version}"]

        if has_serve:
            try:
                importlib.import_module(f"{import_name}.serve")
                parts.append("serve: yes")
            except ImportError:
                parts.append("serve: no (install [mcp] extra)")

        for extra_import, extra_label in extras:
            try:
                importlib.import_module(extra_import)
                parts.append(f"{extra_label}: yes")
            except ImportError:
                parts.append(f"{extra_label}: no")

        report.checks.append(Check(display_name, "ok", ", ".join(parts), "packages"))
    except ImportError:
        # Check if package exists on disk even if not in this venv
        pkg_dir = _find_package_dir(display_name)
        if pkg_dir:
            # Package exists but isn't installed in this venv — that's normal
            # for multi-venv monorepo. Read version from the package layout or pyproject.
            version = _read_package_version(pkg_dir, import_name)
            status = "ok"
            msg = f"{display_name} {version} (separate venv)"
            if has_serve:
                msg += ", serve: yes"
            report.checks.append(Check(display_name, status, msg, "packages"))
        elif import_name.startswith("kaos_nlp") or import_name.startswith("kaos_ref"):
            report.checks.append(
                Check(display_name, "warn", f"{display_name} not installed (optional)", "packages")
            )
        else:
            report.checks.append(
                Check(display_name, "fail", f"{display_name} not installed", "packages")
            )


def _check_credentials(report: DoctorReport) -> None:
    """Check credential env vars."""
    # Deduplicate by checking if either new or legacy form is set
    seen: dict[str, bool] = {}
    for env_var, display_name, _required in _CREDENTIALS:
        # Group by display name base (strip " (new)")
        base = display_name.replace(" (new)", "")
        if base in seen:
            continue
        value = os.environ.get(env_var, "")
        if not value:
            # Check legacy form too
            for ev, dn, _ in _CREDENTIALS:
                if dn.replace(" (new)", "") == base and os.environ.get(ev):
                    value = os.environ.get(ev, "")
                    break
        if value:
            redacted = value[:4] + "..." + value[-4:] if len(value) > 12 else "***"
            report.checks.append(Check(base, "ok", f"{base} — set ({redacted})", "credentials"))
        else:
            report.checks.append(Check(base, "warn", f"{base} — not set (optional)", "credentials"))
        seen[base] = bool(value)


def _check_agentic_tools(report: DoctorReport) -> None:
    """Check for agentic CLI tools."""
    for binary, display_name in _AGENTIC_TOOLS:
        path = shutil.which(binary)
        if path:
            report.checks.append(Check(binary, "ok", f"{display_name} available", "agentic"))
        else:
            report.checks.append(Check(binary, "warn", f"{display_name} not installed", "agentic"))


def _check_mcp_configs(report: DoctorReport) -> None:
    """Check if KAOS MCP servers are configured in agentic environments."""
    import json

    # Claude Code: check .mcp.json in cwd
    mcp_json = Path.cwd() / ".mcp.json"
    if mcp_json.exists():
        try:
            data = json.loads(mcp_json.read_text())
            servers = data.get("mcpServers", {})
            kaos_servers = [k for k in servers if k.startswith("kaos-")]
            if kaos_servers:
                report.checks.append(
                    Check(
                        "claude-mcp",
                        "ok",
                        f"Claude Code .mcp.json: {len(kaos_servers)} KAOS server(s)",
                        "agentic",
                    )
                )
            else:
                report.checks.append(
                    Check(
                        "claude-mcp",
                        "warn",
                        "Claude Code .mcp.json exists but no KAOS servers (run: kaos setup claude)",
                        "agentic",
                    )
                )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            report.checks.append(
                Check("claude-mcp", "warn", ".mcp.json exists but could not be parsed", "agentic")
            )
    elif shutil.which("claude"):
        report.checks.append(
            Check(
                "claude-mcp",
                "warn",
                "Claude Code available but KAOS not configured (run: kaos setup claude)",
                "agentic",
            )
        )

    # Codex: check ~/.codex/config.toml
    codex_config = Path.home() / ".codex" / "config.toml"
    if codex_config.exists():
        content = codex_config.read_text()
        kaos_count = content.count("[mcp_servers.kaos")
        if kaos_count > 0:
            report.checks.append(
                Check(
                    "codex-mcp",
                    "ok",
                    f"Codex config.toml: {kaos_count} KAOS server(s)",
                    "agentic",
                )
            )
        elif shutil.which("codex"):
            report.checks.append(
                Check(
                    "codex-mcp",
                    "warn",
                    "Codex available but KAOS not configured (run: kaos setup codex)",
                    "agentic",
                )
            )

    # Gemini: check ~/.gemini/settings.json
    gemini_config = Path.home() / ".gemini" / "settings.json"
    if gemini_config.exists():
        try:
            data = json.loads(gemini_config.read_text())
            servers = data.get("mcpServers", {})
            kaos_servers = [k for k in servers if k.startswith("kaos-")]
            if kaos_servers:
                report.checks.append(
                    Check(
                        "gemini-mcp",
                        "ok",
                        f"Gemini settings.json: {len(kaos_servers)} KAOS server(s)",
                        "agentic",
                    )
                )
            elif shutil.which("gemini"):
                report.checks.append(
                    Check(
                        "gemini-mcp",
                        "warn",
                        "Gemini available but KAOS not configured (run: kaos setup gemini)",
                        "agentic",
                    )
                )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            pass


def run_doctor() -> DoctorReport:
    """Run all health checks and return a report."""
    report = DoctorReport()

    # Environment
    _check_python(report)
    _check_uv(report)
    _check_fnm(report)
    _check_node(report)
    _check_pnpm(report)
    _check_git(report)
    _check_docker(report)

    # Core packages
    for import_name, display_name, has_serve, extras in _CORE_PACKAGES:
        _check_package(report, import_name, display_name, has_serve, extras)

    # Serve packages (MCP servers)
    for import_name, display_name, has_serve, extras in _SERVE_PACKAGES:
        _check_package(report, import_name, display_name, has_serve, extras)

    # Optional packages
    for import_name, display_name, has_serve, extras in _OPTIONAL_PACKAGES:
        _check_package(report, import_name, display_name, has_serve, extras)

    # Credentials
    _check_credentials(report)

    # Agentic tools
    _check_agentic_tools(report)
    _check_mcp_configs(report)

    return report


def format_report(report: DoctorReport) -> str:
    """Format the report for human display."""
    lines: list[str] = []
    _STATUS_ICONS = {"ok": "\u2713", "warn": "!", "fail": "\u2717"}

    current_category = ""
    for check in report.checks:
        if check.category != current_category:
            if current_category:
                lines.append("")
            current_category = check.category
            lines.append(f"{current_category.title()}:")

        icon = _STATUS_ICONS.get(check.status, "?")
        lines.append(f"  [{icon}] {check.message}")

    lines.append("")
    lines.append(
        f"Summary: {report.ok_count} ok, {report.warn_count} warnings, {report.fail_count} failures"
    )
    return "\n".join(lines)
