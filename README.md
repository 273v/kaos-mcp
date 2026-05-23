# kaos-mcp

> **Part of [Kelvin Agentic OS](https://kelvin.legal) (KAOS)** — open agentic
> infrastructure for legal work, built by
> [273 Ventures](https://273ventures.com).
> See the [full KAOS package map](https://github.com/273v) for the rest of the stack.

[![PyPI - Version](https://img.shields.io/pypi/v/kaos-mcp)](https://pypi.org/project/kaos-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/kaos-mcp)](https://pypi.org/project/kaos-mcp/)
[![License](https://img.shields.io/pypi/l/kaos-mcp)](https://github.com/273v/kaos-mcp/blob/main/LICENSE)
[![quality](https://github.com/273v/kaos-mcp/actions/workflows/quality.yml/badge.svg)](https://github.com/273v/kaos-mcp/actions/workflows/quality.yml)

`kaos-mcp` is the FastMCP runtime and server bridge of KAOS — it mounts
any [`KaosRuntime`](https://github.com/273v/kaos-core) into the official
Python MCP SDK and exposes its tools, content / tabular / session /
config resources, and structured log stream over **stdio** or
**streamable HTTP**. Tool annotations, `ToolResult` envelopes,
per-request `_meta.kaos_config` overrides, and `kaos.*` log records
flow through the bridge unchanged so MCP clients (Claude Code, Codex,
Gemini, Cursor, VS Code, custom agents) see exactly the contract
documented by `kaos-core`. The package also ships the unified `kaos`
management CLI used by every sibling module for `doctor` / `status` /
`setup` / `serve`.

The base install is intentionally small: seven runtime dependencies
(`httpx`, `kaos-content[markdown]`, `kaos-core`, `mcp[cli]`, `pydantic`,
`pydantic-settings`, `starlette`) and no compiled native code. There
are no optional extras at this release — every adapter (tools,
resources, content templates, tabular templates, config resource,
session resource, log bridge, dynamic `logging/setLevel`, workflow
prompts) is included in the base install. Sibling KAOS modules are
**not** runtime dependencies of `kaos-mcp`; you bring your own
`KaosRuntime` and register whichever modules you have installed.

## Install

```bash
uv add "kaos-mcp>=0.1.0"
# or
pip install "kaos-mcp>=0.1.0"
```

`kaos-mcp` requires Python **3.13** or newer (3.14 is supported). The
package is pure Python, classified `Operating System :: OS Independent`
— it runs anywhere CPython 3.13+ runs (Linux, macOS, Windows).

## Quick start

Build a runtime, register a sibling module's tools, and serve them over
stdio (the transport Claude Code, Codex, and Gemini use by default):

```python
from kaos_core import KaosRuntime
from kaos_pdf import register_pdf_tools

from kaos_mcp import KaosMCPServer, KaosMCPSettings

# 1. Build a runtime and register the tools you want exposed.
runtime = KaosRuntime()
register_pdf_tools(runtime)            # 7 read-only kaos-pdf-* tools

# 2. Configure the server. Every field is overridable via KAOS_MCP_*
#    environment variables or per-request _meta.kaos_config.
settings = KaosMCPSettings(
    name="kaos-pdf-mcp",
    instructions="PDF extraction tools backed by pypdfium2.",
    transport="stdio",
)

# 3. Run the server. run_stdio() blocks; run_streamable_http() boots
#    a Starlette app on settings.host:settings.port mounted at
#    settings.streamable_http_path (default /mcp).
server = KaosMCPServer(runtime=runtime, settings=settings)
server.run_stdio()                     # for Claude Code / Codex / Gemini
# server.run_streamable_http()         # for HTTP / browser-based clients
```

`KaosMCPServer` is the high-level entry point. If you need direct
access to the underlying `FastMCP` app — for example to mount it inside
an existing Starlette / FastAPI service — call `create_app(runtime,
settings)` instead and embed the returned app yourself.

## Concepts

The package is a thin, typed bridge between `kaos-core` and the Python
MCP SDK. The most important entries:

| Concept | Purpose |
|---|---|
| **`KaosMCPServer`** | High-level server wrapper. Constructs a `FastMCP` app from a `KaosRuntime` + `KaosMCPSettings`, and exposes `run_stdio()`, `run_streamable_http()`, and `streamable_http_app()` for embedding in an existing Starlette / FastAPI service. |
| **`KaosMCPSettings`** | `ModuleSettings` subclass driving the bridge. Fields: `name`, `instructions`, `transport` (`stdio` / `streamable-http`), `host`, `port`, `mount_path`, `streamable_http_path`, `debug`, `log_level`, `enable_tools`, `enable_resources`, `json_response`, `stateless_http`, `list_roots_timeout`. Reads `KAOS_MCP_*` env vars; per-request `_meta.kaos_config` overrides flow through `from_context()`. |
| **`create_app(runtime, settings=None)`** | Lower-level builder used by `KaosMCPServer`. Returns a configured `FastMCP` instance with tool, resource, content-template, tabular-template, config, and session adapters wired in, workflow prompts registered, and the dynamic `logging/setLevel` handler installed. |
| **`ToolAdapter`** | Converts `KaosTool` instances to FastMCP tool handlers. Preserves `ToolAnnotations` (readOnlyHint, idempotentHint, destructiveHint, openWorldHint) so MCP clients can auto-approve safe calls. `humanConfirmationRequired` is mirrored into `meta["kaos/human_confirmation_required"]`. Tool errors return `CallToolResult(isError=True)` rather than protocol errors so LLMs can self-correct. |
| **`ResourceAdapter`** | Registers `KaosResource` instances on the FastMCP app. Companion adapters specialise the surface: `ContentResourceAdapter` (12 `kaos://content/{id}/...` templates for AST navigation), `TabularResourceAdapter` (DuckDB / Polars / CSV / Parquet views), `ConfigResourceAdapter` (`kaos://server/config` with auto-redacted `SecretStr` fields), `SessionResourceAdapter` (`kaos://session/{id}/artifacts` index). |
| **`ContextBridge`** | Maps MCP request context to `KaosContext` — propagates `client_id`, `request_id`, `roots`, and the per-request `_meta.kaos_config` dict so `ModuleSettings.from_context()` sees the override. Bridges MCP progress tokens to runtime progress callbacks. `list_roots_timeout` is configurable on `KaosMCPSettings`. |
| **`McpLogHandler`** | Forwards Python log records from the `kaos.*` logger hierarchy to MCP clients as `notifications/message` events during tool execution. Installed via `bridge_logs_to_mcp()` for the duration of each tool call. Honours the dynamic level set by the MCP `logging/setLevel` request; delivery is fire-and-forget via `loop.call_soon_threadsafe()` so logging never blocks tool execution. |

## CLI

`kaos-mcp` ships two console scripts. Both support `--json` on every
structured subcommand for piping into other agents.

**`kaos`** — the unified KAOS management CLI used by every sibling
module. Health checks, status, agentic-environment configuration, and
a smart `serve` that auto-detects installed modules:

```bash
kaos doctor --json                              # environment + credential check
kaos status --json                              # module + server inventory
kaos setup claude --scope project               # write .mcp.json
kaos setup codex                                # write ~/.codex/config.toml
kaos setup gemini --scope user                  # write ~/.gemini/settings.json
kaos serve --module pdf,web,office              # stdio with selected modules
kaos serve --http --port 8000                   # streamable HTTP, all installed
```

Project scaffolding (`kaos new ...`) lives in the separate
[`kaos-ui`](https://github.com/273v/kaos-ui) package — install it and
use `kaos-ui new <kind> <name>` to scaffold FastAPI / Streamlit /
Next.js apps.

**`kaos-mcp`** — the bare server entry point. Use it when you want a
single-process MCP server with explicit module loading and no
management overhead:

```bash
kaos-mcp serve --module pdf                     # stdio, single module
kaos-mcp serve --module pdf,web --http          # streamable HTTP
kaos-mcp list-tools --json                      # registered tools
kaos-mcp list-resources --json                  # registered resources
```

Without `--module`, `kaos-mcp serve` starts with an empty runtime and
prints guidance on how to load tools. Module-specific entrypoints
(`kaos-pdf-serve`, `kaos-web-serve`, ...) are preferred for
single-module use; `kaos-mcp serve` is the right choice when you want
to compose several modules into one server.

## Compatibility & status

| Aspect | |
|---|---|
| **Python** | 3.13, 3.14 |
| **OS** | Linux, macOS, Windows (pure Python — `Operating System :: OS Independent`; no native code) |
| **Maturity** | 0.1.0 GA. The public API is documented in `kaos_mcp.__all__`: `KaosMCPServer`, `KaosMCPSettings`, `create_app`, `__version__`. |
| **Stability policy** | Pre-1.0: minor bumps may change behaviour. Every change is documented in [`CHANGELOG.md`](CHANGELOG.md). The MCP wire surface (tool annotations, resource URI templates, the `kaos://` scheme, `_meta.kaos_config`) and the `KAOS_MCP_*` environment-variable namespace are public API and follow the same policy. After 1.0 we follow semver. |
| **Test coverage** | 147 unit tests (`tests/unit/`) covering config, adapters, log bridge, management commands, and the FastMCP wiring; plus an integration suite (`tests/integration/`) that exercises in-memory MCP sessions and embedded streamable-HTTP mounts end-to-end. |
| **Type checker** | Validated with [`ty`](https://docs.astral.sh/ty/), Astral's Python type checker. |

## Documentation

Per-package reference: see in-tree docstrings and
[CHANGELOG.md](CHANGELOG.md).

Cross-cutting KAOS guides (agentic patterns, persona presets, settings
policy, citations, MCP data flow, migration to 0.1.0 GA) live in
[`kaos-modules/docs/guides/`](https://github.com/273v/kaos-modules/tree/main/docs/guides).

## Companion packages

`kaos-mcp` is one of the packages in the
[Kelvin Agentic OS](https://kelvin.legal). The broader stack:

| Package | Layer | What it does |
|---|---|---|
| [`kaos-core`](https://github.com/273v/kaos-core) | Core | Foundational runtime, MCP-native types, registries, execution engine, VFS |
| [`kaos-content`](https://github.com/273v/kaos-content) | Core | Typed document AST: Block/Inline, provenance, views |
| [**`kaos-mcp`**](https://github.com/273v/kaos-mcp) | **Bridge** | **FastMCP server, `kaos` management CLI, MCP resource templates** |
| [`kaos-pdf`](https://github.com/273v/kaos-pdf) | Extraction | PDF → AST with provenance |
| [`kaos-web`](https://github.com/273v/kaos-web) | Extraction | Web extraction, browser automation, search, domain intelligence |
| [`kaos-office`](https://github.com/273v/kaos-office) | Extraction | DOCX / PPTX / XLSX readers + writers to AST |
| [`kaos-tabular`](https://github.com/273v/kaos-tabular) | Extraction | DuckDB-powered SQL analytics |
| [`kaos-source`](https://github.com/273v/kaos-source) | Data | Government + financial data connectors (Federal Register, eCFR, EDGAR, GovInfo, PACER, GLEIF) |
| [`kaos-llm-client`](https://github.com/273v/kaos-llm-client) | LLM | Multi-provider LLM transport |
| [`kaos-llm-core`](https://github.com/273v/kaos-llm-core) | LLM | Typed LLM programming (Signatures, Programs, Optimizers) |
| [`kaos-nlp-core`](https://github.com/273v/kaos-nlp-core) | Primitives (Rust) | High-performance NLP primitives |
| [`kaos-nlp-transformers`](https://github.com/273v/kaos-nlp-transformers) | ML | Dense embeddings + retrieval |
| [`kaos-graph`](https://github.com/273v/kaos-graph) | Primitives (Rust) | Graph algorithms + RDF/SPARQL |
| [`kaos-ml-core`](https://github.com/273v/kaos-ml-core) | Primitives (Rust) | Classical ML on the document AST |
| [`kaos-citations`](https://github.com/273v/kaos-citations) | Legal | Legal citation extraction, resolution, verification |
| [`kaos-agents`](https://github.com/273v/kaos-agents) | Agentic | Agent runtime, memory, recipes |
| [`kaos-reference`](https://github.com/273v/kaos-reference) | Sample | Reference module for module authors |

Packages depend on `kaos-core`; everything else is opt-in. Mix and match the
ones you need.

## Development

```bash
git clone https://github.com/273v/kaos-mcp
cd kaos-mcp
uv sync --group dev
```

Install pre-commit hooks (recommended — they run the same checks as CI on
every commit, scoped to staged files):

```bash
uvx pre-commit install
uvx pre-commit run --all-files     # one-time full sweep
```

Manual QA commands (the same set CI runs):

```bash
uv run ruff format --check kaos_mcp tests
uv run ruff check kaos_mcp tests
uv run ty check kaos_mcp tests
uv run pytest tests/unit -q
```

## Build from source

```bash
uv build
uv pip install dist/*.whl
python -c "import kaos_mcp; print(kaos_mcp.__version__)"  # smoke import
```

## Contributing

Issues and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md)
for setup, quality gates, pull request expectations, and engineering
standards. By contributing you agree to follow the
[project conduct expectations](CODE_OF_CONDUCT.md) and certify the
[Developer Certificate of Origin v1.1](https://developercertificate.org/) —
sign every commit with `git commit -s`. Please open an issue before starting
on a non-trivial change so we can align on scope.

## Security

For security issues, **please do not file a public issue**. Report privately
via [GitHub Private Vulnerability Reporting](https://github.com/273v/kaos-mcp/security/advisories/new)
or email **security@273ventures.com**. See [SECURITY.md](SECURITY.md) for the
full disclosure policy.

## License

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).

Copyright 2026 [273 Ventures LLC](https://273ventures.com).
Built for [kelvin.legal](https://kelvin.legal).
