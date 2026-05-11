# Changelog

All notable changes to `kaos-mcp` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).


## [Unreleased]

### Fixed

- Drift in `_KNOWN_TOOL_COUNTS["kaos-content"]`: bumped from 9 → 17 to match
  `kaos-content` 0.1.0a6 paired with `kaos-core` 0.1.0a5. The
  compatibility-tool layer in `kaos-content` grew from 9 to 17
  registered tools across 0.1.0a5/a6 (new entity-filter and corpus
  analysis tools). The drift-guard test
  (`tests/unit/test_management.py::TestStatus::test_known_tool_counts_match_live_register`)
  was failing in CI's `min-deps` job because under
  `--resolution=lowest-direct` both kaos-content and kaos-core drop
  to their floors, and the older-kaos-core path exposes more
  compatibility tools. Files: `kaos_mcp/management/status.py`.

## [0.1.0a3] — 2026-05-11

### Fixed

- Drift in `_KNOWN_TOOL_COUNTS["kaos-content"]`: bumped from 8 → 9 to match
  `kaos-content` 0.1.0a4, which added `DedupSemanticTool`. The drift-guard
  test (`tests/unit/test_management.py::TestStatus::test_known_tool_counts_match_live_register`)
  was failing in the `min-deps` CI job. Files: `kaos_mcp/management/status.py`.
### Security

- **vulture (dead-code scan) now runs in pre-commit + CI alongside
  the existing bandit job.** New `vulture` hook in
  ``.pre-commit-config.yaml`` mirrored by a new ``vulture (dead-code
  scan)`` job in ``security.yml``. `--min-confidence 100` with the
  shared `--ignore-names` list for names vulture can't infer from
  the import graph (framework callbacks, OAuth/OIDC field names,
  signal handlers, MCP `_meta` keys). Also lands the existing
  bandit hook in pre-commit (it was only in CI before). Both pass
  clean. Mirrors the rollout from kaos-core.
### Changed

- **uv.lock bumped to ``kaos-core`` 0.1.0a4 → 0.1.0a5.** Pure
  lockfile refresh; ``kaos-core`` 0.1.0a5 adds CLI verbs for
  credential management (F2.5) + per-package compatibility fixes.
  kaos-mcp's public API is unaffected. 143 unit tests pass.

## [0.1.0a2] — 2026-05-08

Patch release closing the eight findings in `docs/audit-02/kaos-mcp.md`
(audit-02 F1–F8). No public-API removals; one new optional setting
(`expose_server_config`) opts into the diagnostic config resource that
was previously always-on. Existing `KaosMCPSettings` fields gained three
DoS-cap defaults (`max_resource_bytes`, `max_range_length`,
`max_table_rows`).

### Security

- **F1: per-session artifact isolation enforced at the MCP boundary.**
  Every artifact / content / tabular / session resource handler now
  derives the caller's session via `caller_session_id(ctx)` (prefers
  `ctx.client_id`, falls back to `ctx.request_id`) and passes it as
  `caller_session_id=` into `runtime.artifacts.*` reads. Cross-session
  reads return a uniform `ResourceError("Unknown artifact")` so probing
  cannot enumerate other sessions. `kaos://session/{session_id}/artifacts`
  also refuses to enumerate any session other than the caller's.
  Regression coverage: `tests/unit/test_session_enforcement.py` (10
  tests). Files: `kaos_mcp/adapters/{session,resource,content,tabular,context}.py`.
- **F3: `kaos://server/config` is opt-in and redaction is hardened.**
  New `KaosMCPSettings.expose_server_config` (default `False`) gates
  registration. When enabled, `_redact_value` always emits the constant
  `"***"` (no `first4...last4` partial disclosure), and `_dump_settings`
  redacts plain-`str` fields whose names match
  `token|password|api_key|secret|credential|auth`. Regression coverage:
  `tests/unit/test_config_resource.py` (15 tests including legacy
  plain-`str` credential names). Files:
  `kaos_mcp/{config,app}.py`, `kaos_mcp/adapters/config_resource.py`.
- **F4: resource read DoS caps.** New settings
  `max_resource_bytes` (10 MiB), `max_range_length` (10 MiB), and
  `max_table_rows` (100 000) bound every artifact / content / tabular
  read at the MCP boundary. `kaos://artifacts/{id}/range/{start}/{length}`
  rejects oversize ranges; content-document and tabular-json reads
  surface the artifact store's "Artifact exceeds inline read limit"
  error; `kaos://tabular/{id}/table/{name}/rows/{start}/{count}`
  rejects oversize row counts. Regression coverage:
  `tests/unit/test_resource_caps.py`. Files:
  `kaos_mcp/config.py`, `kaos_mcp/adapters/{resource,content,tabular}.py`.
- **F5: `GOVINFO_API_KEY` written as env reference, not resolved value.**
  `kaos_mcp/management/setup.py:_server_entries` now persists the
  literal `${GOVINFO_API_KEY}` token into `.mcp.json`, `.codex/config.toml`,
  `.gemini/settings.json`, `.vscode/mcp.json`, and `.cursor/mcp.json`.
  Claude Code, Codex CLI, and Gemini CLI expand the reference at agent
  launch — the project-local config never carries plaintext secrets.
  Regression coverage: `tests/unit/test_management.py::TestSetup`
  (`test_govinfo_*`, `test_setup_claude_writes_env_reference_not_secret`).
- **F6: `kaos setup env` requires `--yes` for installer pipelines and
  drops cwd-based script discovery.** `_find_setup_script` now walks
  only from `__file__` (no more `Path.cwd()` fallback that would have
  executed any nearby `scripts/setup-env.sh`). Direct
  `curl … | sh` invocations against `https://astral.sh/uv/install.sh`
  and `https://fnm.vercel.app/install` now require explicit
  confirmation (CLI `--yes` flag, `confirm=True` from code); without
  it the command is reported but not run. Regression coverage:
  `tests/unit/test_management.py::TestSetup` (`test_setup_env_*`,
  `test_find_setup_script_does_not_use_cwd`). Files:
  `kaos_mcp/management/{env,cli}.py`.
- **F7: CI supply-chain hardening.** `.github/workflows/security.yml`
  pins the gitleaks Docker image to `v8.21.2` (no longer `:latest`),
  adds a Bandit static-analysis job (medium severity / medium
  confidence, AST-level), and runs the integration suite on
  `schedule` and `workflow_dispatch`. SHA-pinning of GitHub Actions
  themselves remains a follow-up; the existing
  `.github/dependabot.yml` `github-actions` ecosystem PRs continue to
  keep tag-pinned actions current.

### Changed

- **F2 + F8: `SECURITY.md` rewritten to match the actual surface.**
  The previous file referenced `ProgramOfThought`, `batch_run`, the
  semantic cache, and Program v3 — all of which live in
  `kaos-llm-core` / `kaos-agents`, not `kaos-mcp`. The new file
  documents the real boundaries (MCP transport, request validation,
  per-session artifact enforcement, opt-in config resource, DoS caps,
  setup helpers, OIDC release pipeline) and adds an explicit threat
  model section explaining that per-request `_meta.kaos_config`
  overrides are accepted as-is and that `kaos-mcp` should only be
  exposed to trusted clients (stdio, or streamable HTTP behind an
  authenticating proxy). Closes audit-02 F2 (documented threat model)
  and F8 (scope alignment).

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

[Unreleased]: https://github.com/273v/kaos-mcp/compare/v0.1.0a3...HEAD
[0.1.0a3]: https://github.com/273v/kaos-mcp/compare/v0.1.0a2...v0.1.0a3
[0.1.0a2]: https://github.com/273v/kaos-mcp/compare/v0.1.0a1...v0.1.0a2
[0.1.0a1]: https://github.com/273v/kaos-mcp/releases/tag/v0.1.0a1
