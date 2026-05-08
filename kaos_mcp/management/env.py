"""Environment setup — install uv, Python, fnm, Node.js, pnpm.

Cross-platform toolchain installation. Delegates to the shell script
for actual installation, or calls tools directly when possible.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any


def _run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    """Run a command and return the result."""
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120, **kwargs)


def _which(name: str) -> str | None:
    return shutil.which(name)


def _find_setup_script() -> Path | None:
    """Find scripts/setup-env.sh in the kaos-modules repo."""
    current = Path(__file__).resolve()
    for parent in current.parents:
        script = parent / "scripts" / "setup-env.sh"
        if script.exists():
            return script
    # Also check cwd
    cwd_script = Path.cwd() / "scripts" / "setup-env.sh"
    if cwd_script.exists():
        return cwd_script
    return None


def setup_env(
    *,
    python_version: str = "3.14",
    node_version: str = "24",
    skip_node: bool = False,
    skip_python: bool = False,
    dry_run: bool = False,
) -> list[str]:
    """Install the KAOS development toolchain.

    Prefers the shell script (scripts/setup-env.sh) when available.
    Falls back to direct tool invocation.

    Returns list of actions taken.
    """
    script = _find_setup_script()

    if script and platform.system() != "Windows":
        return _setup_via_script(
            script,
            python_version=python_version,
            node_version=node_version,
            skip_node=skip_node,
            skip_python=skip_python,
            dry_run=dry_run,
        )

    return _setup_direct(
        python_version=python_version,
        node_version=node_version,
        skip_node=skip_node,
        skip_python=skip_python,
        dry_run=dry_run,
    )


def _setup_via_script(
    script: Path,
    *,
    python_version: str,
    node_version: str,
    skip_node: bool,
    skip_python: bool,
    dry_run: bool,
) -> list[str]:
    """Run the shell setup script."""
    cmd = ["bash", str(script)]
    cmd.extend(["--python", python_version])
    cmd.extend(["--node", node_version])
    if skip_node:
        cmd.append("--skip-node")
    if skip_python:
        cmd.append("--skip-python")
    if dry_run:
        cmd.append("--dry-run")

    # Stream output directly to terminal
    result = subprocess.run(cmd, timeout=600)
    if result.returncode == 0:
        return ["Setup completed via setup-env.sh"]
    return [f"Setup script failed with exit code {result.returncode}"]


def _setup_direct(
    *,
    python_version: str,
    node_version: str,
    skip_node: bool,
    skip_python: bool,
    dry_run: bool,
) -> list[str]:
    """Direct tool installation (fallback when script not available)."""
    actions: list[str] = []
    is_windows = platform.system() == "Windows"

    if not skip_python:
        # Install uv
        if not _which("uv"):
            if dry_run:
                actions.append("Would install uv")
            elif is_windows:
                actions.append("Run in PowerShell: irm https://astral.sh/uv/install.ps1 | iex")
            else:
                result = subprocess.run(
                    ["bash", "-c", "curl -LsSf https://astral.sh/uv/install.sh | sh"],
                    timeout=120,
                )
                actions.append("Installed uv" if result.returncode == 0 else "Failed to install uv")
        else:
            actions.append("uv already installed")

        # Install Python
        if _which("uv"):
            if dry_run:
                actions.append(f"Would install Python {python_version}")
            else:
                result = _run(["uv", "python", "install", python_version])
                if result.returncode == 0:
                    actions.append(f"Python {python_version} installed")
                else:
                    actions.append(f"Python {python_version} already available")

    if not skip_node:
        # Install fnm
        if not _which("fnm"):
            if dry_run:
                actions.append("Would install fnm")
            elif is_windows:
                actions.append("Run: winget install Schniz.fnm")
            else:
                result = subprocess.run(
                    [
                        "bash",
                        "-c",
                        "curl -fsSL https://fnm.vercel.app/install | bash -s -- --skip-shell",
                    ],
                    timeout=120,
                )
                actions.append(
                    "Installed fnm" if result.returncode == 0 else "Failed to install fnm"
                )
        else:
            actions.append("fnm already installed")

        # Install Node.js
        if _which("fnm"):
            if dry_run:
                actions.append(f"Would install Node.js {node_version}")
            else:
                result = _run(["fnm", "install", node_version])
                actions.append(
                    f"Node.js {node_version} installed"
                    if result.returncode == 0
                    else f"Node.js {node_version} already available"
                )

        # Install pnpm
        if not _which("pnpm") and _which("corepack"):
            if dry_run:
                actions.append("Would install pnpm via corepack")
            else:
                result = _run(["corepack", "enable", "pnpm"])
                actions.append(
                    "pnpm installed via corepack"
                    if result.returncode == 0
                    else "Failed to install pnpm"
                )
        elif _which("pnpm"):
            actions.append("pnpm already installed")

    return actions
