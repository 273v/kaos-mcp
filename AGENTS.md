# Repository Agent Guidance

## Scope

This file is the canonical coding-agent instruction file for this repository. It
applies to automated and human-assisted coding agents working in the public
`kaos-mcp` repository. Keep changes narrowly scoped, preserve existing user
changes, and prefer links to repository standards over duplicating policy.

For contributor workflow and detailed standards, read:

- [CONTRIBUTING.md](CONTRIBUTING.md)
- [Python design and architecture](docs/standards/python-design-and-architecture.md)
- [Code quality standards](docs/standards/code-quality-standards.md)
- [Engineering process](docs/standards/engineering-process.md)
- [Tests, fixtures, and CI](docs/standards/tests-fixtures-ci.md)

## Project Identity

- Distribution: `kaos-mcp`
- Import package: `kaos_mcp`
- CLI entry points: `kaos` and `kaos-mcp`
- Runtime floor: Python 3.13+
- Environment and packaging tool: `uv`
- Format and lint: `ruff`
- Type checker: `ty`, not mypy
- Test runner: `pytest`

`kaos-mcp` is a pure-Python FastMCP bridge that exposes a `KaosRuntime` over MCP
stdio or streamable HTTP. Treat the documented MCP surface, CLI behavior,
environment-variable namespace, schemas, resource URI templates, and package
exports as public contracts.

## Setup

Use the repository-local development setup:

```bash
uv sync --group dev
uvx pre-commit install
```

Do not hand-edit generated files, lockfiles, release metadata, or dependency
metadata unless the task explicitly requires that surface.

## Local Checks

Before proposing code changes, run the relevant cheap gate from
[CONTRIBUTING.md](CONTRIBUTING.md):

```bash
uv run ruff format --check kaos_mcp tests
uv run ruff check kaos_mcp tests
uv run ty check kaos_mcp tests
uv run pytest tests/unit -q --no-cov
```

For broader behavior changes, prefer the marker-based local gate documented in
[tests, fixtures, and CI](docs/standards/tests-fixtures-ci.md):

```bash
uv run pytest -m "not live and not network and not slow" --no-cov
```

For packaging, metadata, README rendering, or release behavior changes, also run:

```bash
uv build
uvx --from twine twine check --strict dist/*
```

If a check is impractical, report the exact reason and the risk left unverified.

## Architecture Rules

- Keep the bridge thin: `kaos_mcp` adapts `KaosRuntime` to FastMCP without
  reimplementing runtime behavior owned by `kaos-core`.
- Preserve public MCP wire contracts. Changes to tool names, schemas,
  annotations, resource names, resource URI templates, prompts, error shapes,
  `_meta` behavior, CLI JSON output, or `KAOS_MCP_*` settings need tests, docs,
  and changelog consideration.
- Preserve `ToolAnnotations` when converting runtime tools to FastMCP tools,
  including read-only, idempotent, destructive, and open-world safety hints.
  Keep `humanConfirmationRequired` mirrored in tool metadata.
- Keep tool schemas agent-friendly and flat where possible. Avoid nested or
  dynamic input shapes unless the runtime contract already requires them.
- Thread request settings through `ModuleSettings.from_context` by preserving
  `_meta.kaos_config` propagation into `KaosContext`.
- Preserve `kaos://` resource and template behavior for artifacts, content,
  tabular data, session artifacts, and optional server configuration. Keep
  resource reads bounded and session-aware.
- Keep MCP log bridging scoped to tool execution. Preserve the `kaos.*` log
  bridge, dynamic `logging/setLevel`, and non-blocking log delivery behavior.
- Return agent-readable tool failures as tool results when appropriate so MCP
  clients can self-correct. Reserve protocol errors for protocol/resource
  failures.
- Keep configuration typed in `KaosMCPSettings`, sourced through
  `ModuleSettings`, and exposed only when intentionally enabled. Secret values
  must remain redacted in diagnostic resources and outputs.
- Avoid import-time side effects: no network calls, filesystem scans, logging
  setup, provider initialization, or expensive runtime construction at import
  time.

## Testing

- Add or update tests for public behavior, bug fixes, MCP contracts, CLI output,
  configuration resolution, security-sensitive boundaries, and error shapes.
- Prefer tests through the real public entry point over mocked-only tests for
  public API behavior.
- Keep unit tests deterministic and free of network, credentials, local
  services, and large downloads.
- Use `ty` ignore syntax only when needed: `# ty: ignore[...]`. Do not use mypy
  `# type: ignore[...]` as a substitute.

## Security

- Do not commit secrets, credentials, tokens, `.env` files, private keys,
  customer data, or privileged content.
- Preserve bounds around resource sizes, range reads, table rows, roots,
  artifact sessions, paths, URLs, subprocesses, and any untrusted input.
- Keep error messages useful but avoid leaking credentials, internal paths,
  stack traces, or sensitive deployment details.
- Do not discuss suspected vulnerabilities in public issues. Follow
  [SECURITY.md](SECURITY.md).

## Commits, PRs, And Releases

- Use conventional commit style and sign commits with DCO sign-off
  (`git commit -s`).
- Keep PRs to one logical change, rebase on `main`, and document what changed,
  why, and how it was tested.
- Update `CHANGELOG.md` for user-visible changes, including public API, CLI
  behavior, MCP wire contracts, schema output, package metadata, security
  behavior, and deprecations.
- Do not move public tags. Do not force-push protected or shared branches.
- Release work must follow
  [engineering process](docs/standards/engineering-process.md) and the packaging
  gates in [code quality standards](docs/standards/code-quality-standards.md).
