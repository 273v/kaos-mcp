# Security policy

## Reporting a vulnerability

We take security seriously. If you believe you have found a security
vulnerability in `kaos-mcp`, please report it privately so we can address it
before public disclosure.

**Please do not file a public GitHub issue for security reports.**

### How to report

Use [GitHub Private Vulnerability Reporting](https://github.com/273v/kaos-mcp/security/advisories/new)
to send a report. Alternatively, email **security@273ventures.com**.

Include as much of the following as you can:

- A description of the vulnerability and its impact
- Steps to reproduce, including affected versions
- Any proof-of-concept code, if available
- Suggested mitigations, if you have any

### What to expect

- **Acknowledgement** — within 3 business days of your report.
- **Initial triage** — within 7 business days, including a severity assessment.
- **Fix and disclosure** — coordinated with you. Our target window is 90 days
  from acknowledgement to public disclosure, faster for high-severity issues.
- **Credit** — we credit reporters in the release notes and security advisory
  unless you prefer to remain anonymous.

## Supported versions

`kaos-mcp` follows Semantic Versioning. While the project is pre-1.0, only
the latest minor release receives security fixes. After 1.0, the latest two
minor releases will be supported.

| Version | Supported |
|---------|-----------|
| 0.1.x   | Yes       |
| < 0.1   | No        |

## Threat model

`kaos-mcp` is the FastMCP server bridge for any `KaosRuntime`. It exposes
tools and read-only resources (artifacts, content documents, tabular
documents, session indexes) over stdio or streamable HTTP.

The model assumes a **trusted, single-tenant client** unless the operator
takes additional steps:

- **stdio transport** — the parent process is the client. Trust boundary
  is the OS user. This is the default and recommended deployment.
- **streamable HTTP transport** — every connecting client sees the same
  `KaosRuntime`. Treat any HTTP listener as authenticated infrastructure;
  do not expose it directly to untrusted networks. Use a reverse proxy
  with auth (mTLS, OAuth, IP allowlist) when publishing remotely.

Per-session isolation in this server is enforced **between concurrent MCP
clients on the same runtime**, not as a substitute for transport-level
auth. Specifically:

- **Artifacts are session-bound.** All resource templates derive the
  caller's session from `ctx.client_id` (with `ctx.request_id` fallback)
  and pass it to `runtime.artifacts.*` as `caller_session_id=`. Reads
  for artifacts owned by a different session return a uniform "Unknown
  artifact" error so probing cannot enumerate other sessions.
- **`_meta.kaos_config` overrides are trusted.** Each MCP request may
  set `_meta.kaos_config` to a dict that flows into per-request
  `ModuleSettings.from_context()` overrides (`ContextBridge.create_kaos_context`).
  This is intentional — it lets a trusted agent vary safety / verbosity /
  network knobs per request. **Do not deploy `kaos-mcp` where untrusted
  clients can connect:** an attacker that controls request `_meta` can
  weaken any module setting that participates in `from_context()`. If
  you need a hardened multi-tenant surface, gate the server behind an
  authenticating proxy, or fork to allowlist specific override keys.
- **`kaos://server/config` is opt-in.** The diagnostic config resource
  is **not** registered by default. Set
  `KAOS_MCP_EXPOSE_SERVER_CONFIG=1` (or
  `expose_server_config=True` in code) to enable it. When enabled, the
  resource redacts `SecretStr` fields and any field whose name matches
  `token|password|api_key|secret|credential|auth` to a constant `"***"`.
- **Resource read sizes are bounded.** Settings cap maximum bytes
  returned per artifact / range / tabular row request. See the
  `max_resource_bytes`, `max_range_length`, and `max_table_rows`
  fields on `KaosMCPSettings`.

## Operator guidance

- **Local development / single-user agent:** stdio is sufficient.
- **Networked multi-process deployment:** prefer stdio over a Unix
  socket from a trusted launcher. If using streamable HTTP, terminate
  TLS and authentication upstream; do not bind directly to `0.0.0.0`.
- **Telemetry and config diagnostics:** keep `expose_server_config=False`
  in production. Enable temporarily under access control if needed.
- **Auto-configuration of agent tools (`kaos setup ...`):** the setup
  helpers write env-var references like `${GOVINFO_API_KEY}` rather
  than persisting resolved secrets to disk. Inspect generated
  `.mcp.json`, `~/.codex/config.toml`, etc. before committing them to
  source control.
- **Toolchain bootstrap (`kaos setup env`):** invokes upstream
  installer scripts (`astral.sh/uv`, `fnm.vercel.app`) via
  `curl | sh`. These are user-initiated and require explicit
  confirmation. Review the printed installer URL and prefer your
  package manager (`apt`, `brew`, `winget`) when available.

## Scope

In-scope:

- The `kaos-mcp` Python package as published on PyPI
- The `273v/kaos-mcp` GitHub repository (CI, release, supply chain)
- Request validation at the FastMCP boundary (tool args, resource URIs)
- Tool annotation enforcement (`readOnlyHint`, `destructiveHint`,
  `humanConfirmationRequired`) as exposed via `ToolAdapter`
- Per-session artifact isolation (resource templates under
  `kaos://artifacts/`, `kaos://content/`, `kaos://tabular/`,
  `kaos://session/`)
- Resource read size caps (`max_resource_bytes`, `max_range_length`,
  `max_table_rows`)
- Opt-in diagnostic config resource (`kaos://server/config`) and its
  redaction logic
- Auto-setup helpers (`kaos setup claude|codex|gemini|vscode|cursor`)
  and toolchain bootstrap (`kaos setup env`)
- OIDC trusted-publishing release pipeline

Out of scope:

- Vulnerabilities in third-party dependencies — report upstream
  (`pydantic`, `mcp`, `kaos-core`, `kaos-content`, `starlette`,
  `httpx`).
- Provider-side issues at OpenAI / Anthropic / Google / xAI / Groq /
  Mistral / OpenRouter — report to the upstream provider; these are
  surfaced through `kaos-llm-client` which lives in its own repo.
- Issues caused by user-supplied configuration that explicitly disables
  safety features — for example, deploying streamable HTTP on an
  untrusted network without an authenticating proxy, or enabling
  `expose_server_config=True` in a multi-tenant environment.
- Tool-level vulnerabilities in sibling packages (`kaos-pdf`,
  `kaos-web`, `kaos-office`, `kaos-tabular`, `kaos-source`,
  `kaos-graph`, `kaos-llm-core`, `kaos-agents`) — report to those
  individual repositories.
