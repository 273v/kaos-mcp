"""Environment setup — install uv, Python, fnm, Node.js, pnpm.

Cross-platform toolchain installation. Delegates to the in-tree shell
script (``scripts/setup-env.sh`` co-located with the kaos-modules
checkout) for monorepo runs, or calls upstream installers directly when
running outside the monorepo.

audit-02 F6 hardening:

- ``_find_setup_script`` discovers ``scripts/setup-env.sh`` only by
  walking from this module's ``__file__``, never from ``Path.cwd()``.
  The cwd-based fallback was a path-confused execution surface — any
  directory containing a ``scripts/setup-env.sh`` would have been
  invoked.
- Direct ``curl | sh`` pipelines now require explicit confirmation
  (``confirm=True`` from code, or ``--yes`` from the CLI). Without
  confirmation the installer command is printed and the action lists
  what would be run, but no network fetch is performed.
- The exact installer URLs invoked are documented inline below and in
  ``SECURITY.md``.

Installer endpoints (require explicit confirmation):

- ``https://astral.sh/uv/install.sh`` — Astral uv installer
- ``https://fnm.vercel.app/install`` — Schniz fnm installer

Operators that prefer their package manager (``apt``, ``brew``,
``winget``) should install ``uv``, ``fnm``, and ``pnpm`` directly and
skip ``kaos setup env`` entirely.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any

UV_INSTALLER_URL = "https://astral.sh/uv/install.sh"
FNM_INSTALLER_URL = "https://fnm.vercel.app/install"
MIN_HARDENED_PNPM_VERSION = "11.1.0"


def _run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    """Run a command and return the result."""
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120, **kwargs)


def _which(name: str) -> str | None:
    return shutil.which(name)


def _parse_semver(version: str) -> tuple[int, int, int] | None:
    """Parse a simple semver prefix from command output."""
    match = version.strip().lstrip("v").split()[0].split("+", 1)[0].split("-", 1)[0]
    parts = match.split(".")
    if len(parts) < 2:
        return None
    try:
        major = int(parts[0])
        minor = int(parts[1])
        patch = int(parts[2]) if len(parts) > 2 else 0
    except ValueError:
        return None
    return major, minor, patch


def _version_lt(current: str, minimum: str) -> bool:
    """Return True when ``current`` is lower than ``minimum``."""
    parsed_current = _parse_semver(current)
    parsed_minimum = _parse_semver(minimum)
    if parsed_current is None or parsed_minimum is None:
        return True
    return parsed_current < parsed_minimum


def _find_setup_script() -> Path | None:
    """Find ``scripts/setup-env.sh`` adjacent to this package's checkout.

    Walks ancestors of ``__file__`` only — never ``Path.cwd()`` (F6).
    Returns ``None`` outside the monorepo so the caller falls back to the
    direct-installer path (which itself requires explicit confirmation).
    """
    current = Path(__file__).resolve()
    for parent in current.parents:
        script = parent / "scripts" / "setup-env.sh"
        if script.exists():
            return script
    return None


def setup_env(
    *,
    python_version: str = "3.14",
    node_version: str = "24",
    pnpm_version: str = MIN_HARDENED_PNPM_VERSION,
    skip_node: bool = False,
    skip_python: bool = False,
    dry_run: bool = False,
    confirm: bool = False,
) -> list[str]:
    """Install the KAOS development toolchain.

    Prefers ``scripts/setup-env.sh`` co-located with the kaos-modules
    checkout (monorepo path). Falls back to direct upstream installers
    when running outside the monorepo. Direct installer fetches require
    ``confirm=True`` (audit-02 F6) — without confirmation the helper
    reports what *would* be run and exits.

    Returns list of actions taken.
    """
    script = _find_setup_script()

    if script and platform.system() != "Windows":
        return _setup_via_script(
            script,
            python_version=python_version,
            node_version=node_version,
            target_pnpm_version=pnpm_version,
            skip_node=skip_node,
            skip_python=skip_python,
            dry_run=dry_run,
        )

    return _setup_direct(
        python_version=python_version,
        node_version=node_version,
        target_pnpm_version=pnpm_version,
        skip_node=skip_node,
        skip_python=skip_python,
        dry_run=dry_run,
        confirm=confirm,
    )


def _setup_via_script(
    script: Path,
    *,
    python_version: str,
    node_version: str,
    target_pnpm_version: str,
    skip_node: bool,
    skip_python: bool,
    dry_run: bool,
) -> list[str]:
    """Run the shell setup script."""
    cmd = ["bash", str(script)]
    cmd.extend(["--python", python_version])
    cmd.extend(["--node", node_version])
    cmd.extend(["--pnpm", target_pnpm_version])
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
    target_pnpm_version: str,
    skip_node: bool,
    skip_python: bool,
    dry_run: bool,
    confirm: bool = False,
) -> list[str]:
    """Direct tool installation (fallback when script not available).

    F6: ``curl | sh`` pipelines require ``confirm=True`` (CLI: ``--yes``).
    Without confirmation, the installer URL is reported and no network
    fetch happens.
    """
    actions: list[str] = []
    is_windows = platform.system() == "Windows"

    if not skip_python:
        # Install uv
        if not _which("uv"):
            if dry_run:
                actions.append(f"Would install uv from {UV_INSTALLER_URL}")
            elif is_windows:
                actions.append("Run in PowerShell: irm https://astral.sh/uv/install.ps1 | iex")
            elif not confirm:
                actions.append(
                    f"uv installer requires --yes; would fetch {UV_INSTALLER_URL} | sh "
                    "(re-run with --yes to confirm, or install via your package manager)"
                )
            else:
                result = subprocess.run(
                    ["bash", "-c", f"curl -LsSf {UV_INSTALLER_URL} | sh"],
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
                actions.append(f"Would install fnm from {FNM_INSTALLER_URL}")
            elif is_windows:
                actions.append("Run: winget install Schniz.fnm")
            elif not confirm:
                actions.append(
                    f"fnm installer requires --yes; would fetch {FNM_INSTALLER_URL} | bash "
                    "(re-run with --yes to confirm, or install via your package manager)"
                )
            else:
                result = subprocess.run(
                    [
                        "bash",
                        "-c",
                        f"curl -fsSL {FNM_INSTALLER_URL} | bash -s -- --skip-shell",
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

        # Install pnpm. KAOS requires pnpm 11.1+ for dependency cooldowns,
        # build-script allowlists, exotic-subdependency blocking, and
        # signature auditing.
        installed_pnpm_version = ""
        if _which("pnpm"):
            result = _run(["pnpm", "--version"])
            installed_pnpm_version = result.stdout.strip() or result.stderr.strip()

        pnpm_missing_or_old = not installed_pnpm_version or _version_lt(
            installed_pnpm_version, target_pnpm_version
        )

        if pnpm_missing_or_old:
            if _which("corepack"):
                if dry_run:
                    actions.append(f"Would activate pnpm {target_pnpm_version} via corepack")
                else:
                    enable = _run(["corepack", "enable", "pnpm"])
                    prepare = _run(
                        ["corepack", "prepare", f"pnpm@{target_pnpm_version}", "--activate"]
                    )
                    actions.append(
                        f"pnpm {target_pnpm_version} activated via corepack"
                        if enable.returncode == 0 and prepare.returncode == 0
                        else f"Failed to activate pnpm {target_pnpm_version}"
                    )
            elif installed_pnpm_version:
                actions.append(
                    f"pnpm {installed_pnpm_version} is older than {target_pnpm_version}; "
                    "install corepack or rerun after upgrading Node.js"
                )
            else:
                actions.append(
                    f"pnpm not installed; install corepack or pnpm >= {target_pnpm_version}"
                )
        else:
            actions.append(f"pnpm already installed ({installed_pnpm_version})")

    return actions
