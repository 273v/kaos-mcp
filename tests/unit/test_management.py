"""Tests for kaos management CLI (doctor, status, setup)."""

from __future__ import annotations

import json
import platform
from pathlib import Path

import pytest

import kaos_mcp.management.doctor as doctor_module
from kaos_mcp.management.cli import main
from kaos_mcp.management.doctor import Check, DoctorReport, format_report, run_doctor
from kaos_mcp.management.env import MIN_HARDENED_PNPM_VERSION, _version_lt
from kaos_mcp.management.setup import _find_kaos_dir, _server_entries
from kaos_mcp.management.status import ModuleInfo, format_status, get_module_status

# ---------------------------------------------------------------------------
# Doctor
# ---------------------------------------------------------------------------


class TestDoctor:
    def test_run_doctor(self) -> None:
        report = run_doctor()
        assert isinstance(report, DoctorReport)
        assert len(report.checks) > 0
        # Should at least check python and uv
        names = {c.name for c in report.checks}
        assert "python" in names
        assert "uv" in names

    def test_python_check_passes(self) -> None:
        report = run_doctor()
        python_check = next(c for c in report.checks if c.name == "python")
        assert python_check.status == "ok"

    def test_kaos_core_detected(self) -> None:
        report = run_doctor()
        core_check = next(c for c in report.checks if c.name == "kaos-core")
        assert core_check.status == "ok"
        assert "0.1" in core_check.message

    def test_kaos_mcp_detected(self) -> None:
        report = run_doctor()
        mcp_check = next(c for c in report.checks if c.name == "kaos-mcp")
        assert mcp_check.status == "ok"

    def test_optional_packages_checked(self) -> None:
        report = run_doctor()
        names = {c.name for c in report.checks}
        assert "kaos-graph" in names
        assert "kaos-llm-client" in names
        assert "kaos-llm-core" in names
        assert "kaos-nlp-core" in names
        assert "kaos-reference" in names

    def test_separate_venv_version_fallback_is_not_unknown(self) -> None:
        report = run_doctor()
        nlp_check = next(c for c in report.checks if c.name == "kaos-nlp-core")
        assert "?" not in nlp_check.message

    def test_credentials_checked(self) -> None:
        report = run_doctor()
        cred_checks = [c for c in report.checks if c.category == "credentials"]
        assert len(cred_checks) > 0

    def test_agentic_tools_checked(self) -> None:
        report = run_doctor()
        agentic_checks = [c for c in report.checks if c.category == "agentic"]
        assert len(agentic_checks) > 0

    def test_pnpm_check_warns_when_version_is_too_old(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            doctor_module.shutil,
            "which",
            lambda name: "/usr/bin/pnpm" if name == "pnpm" else None,
        )
        monkeypatch.setattr(doctor_module, "_run_version_cmd", lambda *cmd: "10.10.0")
        report = DoctorReport()

        doctor_module._check_pnpm(report)

        pnpm_check = report.checks[0]
        assert pnpm_check.status == "warn"
        assert f"need >= {MIN_HARDENED_PNPM_VERSION}" in pnpm_check.message

    def test_pnpm_check_accepts_hardened_version(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            doctor_module.shutil,
            "which",
            lambda name: "/usr/bin/pnpm" if name == "pnpm" else None,
        )
        monkeypatch.setattr(
            doctor_module,
            "_run_version_cmd",
            lambda *cmd: MIN_HARDENED_PNPM_VERSION,
        )
        report = DoctorReport()

        doctor_module._check_pnpm(report)

        pnpm_check = report.checks[0]
        assert pnpm_check.status == "ok"
        assert MIN_HARDENED_PNPM_VERSION in pnpm_check.message

    def test_version_lt_parses_semver_prefixes(self) -> None:
        assert _version_lt("10.32.0", MIN_HARDENED_PNPM_VERSION)
        assert not _version_lt("11.1.0+sha512.example", MIN_HARDENED_PNPM_VERSION)

    def test_format_report(self) -> None:
        report = DoctorReport(
            checks=[
                Check("test", "ok", "All good", "general"),
                Check("warn-test", "warn", "Optional missing", "general"),
            ]
        )
        text = format_report(report)
        assert "All good" in text
        assert "Optional missing" in text
        assert "2 ok" in text or "1 ok" in text

    def test_report_to_dict(self) -> None:
        report = DoctorReport(
            checks=[
                Check("test", "ok", "OK", "general"),
            ]
        )
        d = report.to_dict()
        assert d["command"] == "doctor"
        assert d["ok"] == 1
        assert d["total"] == 1

    def test_check_to_dict(self) -> None:
        c = Check("test", "ok", "message", "cat", "detail text")
        d = c.to_dict()
        assert d["name"] == "test"
        assert d["detail"] == "detail text"


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


class TestStatus:
    def test_get_module_status(self) -> None:
        modules = get_module_status()
        assert len(modules) >= 5
        names = {m.name for m in modules}
        assert "kaos-pdf" in names
        assert "kaos-source" in names

    def test_installed_modules_have_tools(self) -> None:
        modules = get_module_status()
        installed = [m for m in modules if m.installed]
        for m in installed:
            assert m.tool_count > 0, f"{m.name} has no tools"
            assert m.version, f"{m.name} has no version"

    def test_format_status(self) -> None:
        modules = [
            ModuleInfo("kaos-test", "kaos_test", "1.0", True, 5, "kaos-test-serve", []),
        ]
        text = format_status(modules)
        assert "kaos-test" in text
        assert "5 tools" in text
        assert "kaos-test-serve" in text

    def test_module_info_to_dict(self) -> None:
        m = ModuleInfo("kaos-pdf", "kaos_pdf", "0.1.0", True, 5, "kaos-pdf-serve", [])
        d = m.to_dict()
        assert d["name"] == "kaos-pdf"
        assert d["tool_count"] == 5

    def test_known_tool_counts_match_live_register(self) -> None:
        """Drift guard for _KNOWN_TOOL_COUNTS.

        The dict is consulted only when a package isn't importable in
        the current venv. For every package we *can* import, assert the
        hard-coded count matches what its register_func would actually
        register against a fresh runtime. Catches the audit-01 MCP-06
        drift recurring.

        Skipped when ``KAOS_SKIP_TOOL_COUNT_DRIFT_GUARD=1`` is set.
        The min-deps CI job sets it because
        ``--resolution=lowest-direct`` drops every dependency to its
        declared floor — including kaos-core — and the older-kaos-core
        path makes kaos-content's ``register_content_tools`` register
        more compatibility tools than the canonical lockfile pairing
        does. The dict documents the count under the LOCKED version
        cross-product; it doesn't claim to hold across every arbitrary
        version pair. Real drift gets caught by the regular matrix
        legs, which don't set this skip variable.
        """
        import importlib
        import os

        if os.environ.get("KAOS_SKIP_TOOL_COUNT_DRIFT_GUARD") == "1":
            pytest.skip(
                "KAOS_SKIP_TOOL_COUNT_DRIFT_GUARD=1 (set by the min-deps "
                "CI gate); see test docstring for why."
            )

        from kaos_core import KaosRuntime

        from kaos_mcp.management.status import _KNOWN_TOOL_COUNTS, _MODULES

        for import_name, display_name, register_func, _serve, _args in _MODULES:
            try:
                mod = importlib.import_module(import_name)
            except ImportError:
                continue
            register_fn = getattr(mod, register_func, None)
            if register_fn is None:
                continue
            live_count = register_fn(KaosRuntime())
            known = _KNOWN_TOOL_COUNTS.get(display_name)
            assert known == live_count, (
                f"_KNOWN_TOOL_COUNTS[{display_name!r}] = {known}, "
                f"but {register_func}() registered {live_count} tools — "
                f"update the dict in management/status.py"
            )


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------


class TestSetupEnv:
    def test_setup_env_dry_run_reports_installer_urls(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """F6: dry-run prints the exact installer URL it would fetch."""
        from kaos_mcp.management import env as env_module

        # Force the "no script found" branch so direct installers are
        # reported, and pretend uv/fnm aren't installed.
        monkeypatch.setattr(env_module, "_find_setup_script", lambda: None)
        monkeypatch.setattr(env_module, "_which", lambda _name: None)

        actions = env_module.setup_env(dry_run=True)
        joined = "\n".join(actions)
        assert env_module.UV_INSTALLER_URL in joined
        assert env_module.FNM_INSTALLER_URL in joined

    def test_setup_env_without_yes_does_not_fetch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """F6: ``confirm=False`` MUST NOT invoke any subprocess.run for
        installer pipelines. Reports what would run instead."""
        from kaos_mcp.management import env as env_module

        monkeypatch.setattr(env_module, "_find_setup_script", lambda: None)
        monkeypatch.setattr(env_module, "_which", lambda _name: None)

        called: list[list[str]] = []

        def _no_subprocess(cmd: list[str], **_kw: object) -> object:
            called.append(cmd)
            raise AssertionError(f"subprocess.run was invoked without --yes confirmation: {cmd}")

        monkeypatch.setattr(env_module.subprocess, "run", _no_subprocess)

        actions = env_module.setup_env(confirm=False, dry_run=False)
        # Confirmation gate: on POSIX the installer pipelines report
        # "requires --yes"; on Windows they report manual package-manager
        # hints (winget / PowerShell `irm`) that do not auto-fetch. Either
        # way the load-bearing F6 invariant is that NO subprocess ran.
        if platform.system() == "Windows":
            assert any(
                ("winget" in a) or ("PowerShell" in a) or ("requires --yes" in a) for a in actions
            ), actions
        else:
            assert any("requires --yes" in a for a in actions), actions
        assert called == []

    def test_setup_env_dry_run_activates_hardened_pnpm(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from kaos_mcp.management import env as env_module

        monkeypatch.setattr(env_module, "_find_setup_script", lambda: None)
        monkeypatch.setattr(
            env_module,
            "_which",
            lambda name: "/usr/bin/corepack" if name == "corepack" else None,
        )

        actions = env_module.setup_env(skip_python=True, dry_run=True)

        assert f"Would activate pnpm {MIN_HARDENED_PNPM_VERSION} via corepack" in actions

    def test_find_setup_script_does_not_use_cwd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """F6: drop the cwd-based discovery — only walk from __file__."""
        from kaos_mcp.management import env as env_module

        # Plant a fake setup-env.sh in cwd. The hardened function must
        # NOT pick it up.
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "setup-env.sh").write_text("#!/bin/bash\necho fake")
        monkeypatch.chdir(tmp_path)

        result = env_module._find_setup_script()
        # Either returns None (no monorepo present) or returns the
        # __file__-derived path. In either case it must not equal the
        # cwd-planted decoy.
        assert result != scripts_dir / "setup-env.sh"


class TestSetup:
    @pytest.fixture(autouse=True)
    def _require_monorepo_layout(self) -> None:
        # ``_find_kaos_dir`` walks up looking for a directory containing
        # both ``kaos-core/`` and ``kaos-mcp/``. That layout exists when
        # the test suite runs inside the kaos-modules monorepo; in the
        # per-module ``273v/kaos-mcp`` repo (and on PyPI consumers) it
        # does not. Skip the whole class in that case — the function
        # itself is correct, the tests just exercise an environment
        # we cannot synthesize from a single-package checkout.
        try:
            _find_kaos_dir()
        except RuntimeError:
            pytest.skip("requires monorepo layout (kaos-core + kaos-mcp siblings)")

    def test_find_kaos_dir(self) -> None:
        kaos_dir = _find_kaos_dir()
        assert (kaos_dir / "kaos-core").is_dir()
        assert (kaos_dir / "kaos-mcp").is_dir()

    def test_server_entries(self) -> None:
        kaos_dir = _find_kaos_dir()
        entries = _server_entries(kaos_dir)
        assert "kaos-pdf" in entries
        assert "kaos-web" in entries
        assert "kaos-source" in entries
        assert entries["kaos-pdf"]["command"] == "uv"
        assert "kaos-pdf-serve" in entries["kaos-pdf"]["args"]

    def test_server_entries_web_has_browser_flag(self) -> None:
        kaos_dir = _find_kaos_dir()
        entries = _server_entries(kaos_dir)
        assert "--browser" in entries["kaos-web"]["args"]
        assert "--crawl" in entries["kaos-web"]["args"]

    def test_govinfo_key_written_as_env_reference_not_resolved_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """audit-02 F5: agent configs must hold a literal ${GOVINFO_API_KEY}
        env reference, never a resolved secret value, regardless of whether
        the variable is currently set in the shell environment."""
        # Even with a "real" key present, the entry must still be the env ref.
        monkeypatch.setenv("GOVINFO_API_KEY", "would-leak-if-resolved-XYZ")
        kaos_dir = _find_kaos_dir()
        entries = _server_entries(kaos_dir)
        env = entries["kaos-source"].get("env", {})
        assert env.get("GOVINFO_API_KEY") == "${GOVINFO_API_KEY}"
        # Defensive — assert the resolved value never appears anywhere.
        serialized = json.dumps(entries)
        assert "would-leak-if-resolved-XYZ" not in serialized

    def test_govinfo_env_reference_present_when_var_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Env reference is generated even when the user has no current value."""
        monkeypatch.delenv("GOVINFO_API_KEY", raising=False)
        kaos_dir = _find_kaos_dir()
        entries = _server_entries(kaos_dir)
        assert entries["kaos-source"]["env"]["GOVINFO_API_KEY"] == "${GOVINFO_API_KEY}"

    def test_setup_claude_writes_env_reference_not_secret(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """End-to-end: setup_claude must persist ``${GOVINFO_API_KEY}``."""
        from kaos_mcp.management.setup import setup_claude

        monkeypatch.setenv("GOVINFO_API_KEY", "would-leak-if-resolved-ABCDEF")
        original_cwd = Path.cwd()
        try:
            import os

            os.chdir(tmp_path)
            setup_claude(force=True)
            mcp_text = (tmp_path / ".mcp.json").read_text()
            assert "${GOVINFO_API_KEY}" in mcp_text
            assert "would-leak-if-resolved-ABCDEF" not in mcp_text
        finally:
            os.chdir(original_cwd)

    def test_setup_claude_force_writes_mcp_json(self, tmp_path: Path) -> None:
        """Test file-based setup (--force skips CLI)."""
        from kaos_mcp.management.setup import setup_claude

        original_cwd = Path.cwd()
        try:
            import os

            os.chdir(tmp_path)
            actions = setup_claude(force=True)
            assert len(actions) >= 5  # 5 servers
            mcp_path = tmp_path / ".mcp.json"
            assert mcp_path.exists()
            data = json.loads(mcp_path.read_text())
            assert "kaos-pdf" in data["mcpServers"]
            assert "kaos-source" in data["mcpServers"]
        finally:
            os.chdir(original_cwd)

    def test_setup_claude_merges_existing(self, tmp_path: Path) -> None:
        """Test non-destructive merge with existing config."""
        import os

        original_cwd = Path.cwd()
        try:
            os.chdir(tmp_path)
            # Create existing config with a non-kaos server
            existing = {
                "mcpServers": {"my-custom-server": {"command": "node", "args": ["server.js"]}}
            }
            (tmp_path / ".mcp.json").write_text(json.dumps(existing))

            from kaos_mcp.management.setup import setup_claude

            setup_claude(force=True)

            data = json.loads((tmp_path / ".mcp.json").read_text())
            # Original server preserved
            assert "my-custom-server" in data["mcpServers"]
            # KAOS servers added
            assert "kaos-pdf" in data["mcpServers"]
        finally:
            os.chdir(original_cwd)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestCLI:
    def test_doctor_json(self, capsys: object) -> None:
        main(["doctor", "--json"])
        # Should not raise; output is JSON

    def test_status_json(self, capsys: object) -> None:
        main(["status", "--json"])

    def test_doctor_human(self, capsys: object) -> None:
        main(["doctor"])

    def test_status_human(self, capsys: object) -> None:
        main(["status"])

    def test_no_command_shows_help(self) -> None:
        # Should exit 0, not crash
        try:
            main([])
        except SystemExit as e:
            assert e.code == 0
