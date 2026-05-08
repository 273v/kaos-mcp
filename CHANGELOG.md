# Changelog

All notable changes to `kaos-mcp` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0a1] — 2026-05-07

First public alpha. FastMCP-native server bridge that wraps any
`KaosRuntime` — tool registry plus content + tabular resource templates —
and exposes them over stdio or streamable HTTP. Closes every finding in
`docs/audit-01/kaos-mcp.md` (MCP-01..MCP-06).

### Added

- **`LICENSE`, `NOTICE`, `CHANGELOG.md`** seeded for the public release.
  License flips from `LicenseRef-Proprietary` to Apache-2.0 via PEP 639
  (`license = "Apache-2.0"`, `license-files = ["LICENSE", "NOTICE"]`).
  PEP 639-superseded `License ::` classifier removed.

- **`tests/unit/test_management.py::TestStatus::test_known_tool_counts_match_live_register`**
  — drift guard that asserts every entry of `_KNOWN_TOOL_COUNTS` matches
  what its module's `register_*_tools(KaosRuntime())` actually registers.
  Catches audit-01 MCP-06 from recurring whenever a sibling adds tools.

### Changed

- **`KaosMCPSettings` now subclasses `kaos_core.config.ModuleSettings`**
  instead of `pydantic_settings.BaseSettings` directly. Picks up the
  KAOS settings hierarchy (per-request `_meta.kaos_config` overrides via
  `from_context()`, `resolve()` classmethod for default-or-passed
  resolution). Closes audit-01 MCP-04. No behavioural change for
  callers; existing 23 unit tests in `test_config.py` /
  `test_config_resource.py` continue to pass.

- **`_KNOWN_TOOL_COUNTS` in `kaos_mcp/management/status.py` refreshed
  to current platform reality** — kaos-content 7→8, kaos-nlp-core
  10→17, kaos-web 31→42, kaos-office 14→17, kaos-source 22→30. The new
  drift-guard test (above) stops these from going stale silently.
  Closes audit-01 MCP-06.

- **`_read_package_version()` in `kaos_mcp/management/doctor.py` now
  reads Rust+PyO3 versions from `Cargo.toml` `[package].version`** and
  applies the Cargo→PEP 440 normalization (`-alpha.N` → `aN`, `-beta.N`
  → `bN`, `-rc.N` → `rcN`). Without this, packages whose version lives
  in `Cargo.toml` (kaos-nlp-core, kaos-graph) reported as `?` in
  `kaos doctor` when running from a separate venv. Closes audit-01
  MCP-02. Regression coverage:
  `tests/unit/test_management.py::TestDoctor::test_separate_venv_version_fallback_is_not_unknown`.

- **`kaos_mcp/management/__init__.py` declares an explicit empty
  `__all__`** per the platform's public-API discipline rule (every
  `__init__.py` declares one). Closes audit-01 MCP-05.

### Removed

- **`kaos new` subcommand and `kaos_mcp/management/scaffold.py` shim**
  — the project-scaffolding command upward-depended on `kaos-ui` (an
  app-layer package), violating the architecture (kaos-mcp sits in Core
  Infrastructure). The `kaos-ui` runtime dependency drove this; cutting
  the subcommand removes the dep entirely. Project scaffolding moves to
  `kaos-ui new <kind> <name>` (kaos-ui already owns its own console
  script). Closes audit-01 MCP-03 — structurally rather than by
  optional-extra workaround. The `module` and `workflow` non-UI
  templates moved alongside, into `kaos-ui/kaos_ui/templates/`. The
  `kaos` umbrella CLI keeps `doctor`, `status`, `setup`, `serve`.

- **`kaos-ui>=0.1.0` removed from `[project.dependencies]`** and from
  `[tool.uv.sources]`. `kaos-mcp` now depends only on `kaos-core`,
  `kaos-content[markdown]`, `mcp[cli]`, `pydantic`, `pydantic-settings`,
  `httpx`, and `starlette` — back to the documented `kaos-mcp ->
  kaos-core, kaos-content` architecture edge.

[Unreleased]: https://github.com/273v/kaos-mcp/compare/v0.1.0a1...HEAD
[0.1.0a1]: https://github.com/273v/kaos-mcp/releases/tag/v0.1.0a1
