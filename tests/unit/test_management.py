"""Tests for kaos management CLI (doctor, status, setup)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kaos_mcp.management.cli import main
from kaos_mcp.management.doctor import Check, DoctorReport, format_report, run_doctor
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
        """
        import importlib

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
