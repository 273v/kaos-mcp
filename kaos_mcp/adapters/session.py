"""Session artifact index resource adapter.

Registers ``kaos://session/{session_id}/artifacts`` — a read-only resource
that lists all artifacts created within a session.  Agents use this to
discover previously fetched pages, documents, and images without needing
to track individual artifact IDs.
"""

from __future__ import annotations

import json
from typing import Any

from kaos_core import KaosRuntime
from mcp.server.fastmcp import Context as FastMCPContext
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ResourceError as FastMCPResourceError

from kaos_mcp.adapters._error_handling import resource_error_from_exception
from kaos_mcp.adapters.context import caller_session_id
from kaos_mcp.config import KaosMCPSettings

SESSION_TEMPLATE_COUNT = 1


class SessionResourceAdapter:
    """Registers session-scoped resource templates on a FastMCP app."""

    def __init__(self, runtime: KaosRuntime, settings: KaosMCPSettings | None = None) -> None:
        self._runtime = runtime
        self._settings = settings or KaosMCPSettings()

    def register_session_templates(self, app: FastMCP) -> int:
        """Register session resource templates. Returns template count."""
        self._register_templates(app)
        return SESSION_TEMPLATE_COUNT

    def _register_templates(self, app: FastMCP) -> None:
        runtime = self._runtime

        @app.resource(
            "kaos://session/{session_id}/artifacts",
            name="session-artifact-index",
            title="Session Artifact Index",
            description=(
                "List all artifacts created in a session. Returns artifact IDs, "
                "names, URIs, sizes, MIME types, and provenance metadata. "
                "Use this to find previously fetched pages, documents, and images."
            ),
            mime_type="application/json",
        )
        async def session_artifacts(session_id: str, ctx: FastMCPContext) -> str:
            try:
                # F1: refuse to enumerate any session other than the caller's.
                # Uniform "Unknown session" error mirrors the artifact store's
                # cross-session denial — never leak existence of other sessions.
                # ``caller`` is ``None`` only outside an active MCP request
                # (in-process / test callers); enforcement bypassed in that
                # case per the trusted-in-process contract.
                caller = caller_session_id(ctx)
                if caller is not None and session_id != caller:
                    raise FastMCPResourceError(
                        f"kaos://session/{session_id}/artifacts: Unknown session"
                    )
                manifests = runtime.artifacts.list_artifacts(session_id=session_id)
                items: list[dict[str, Any]] = [
                    {
                        "artifact_id": m.artifact_id,
                        "name": m.name,
                        "description": m.description,
                        "uri": m.uri,
                        "body_uri": m.body_uri,
                        "mime_type": m.mime_type,
                        "size": m.size,
                        "created_at": m.created_at,
                        "role": m.role.value,
                        "provenance": m.provenance,
                        "metadata": m.metadata,
                    }
                    for m in manifests
                ]
                return json.dumps(
                    {"session_id": session_id, "count": len(items), "artifacts": items},
                    indent=2,
                )
            except FastMCPResourceError:
                raise
            except Exception as exc:
                raise resource_error_from_exception(
                    exc, context=f"kaos://session/{session_id}/artifacts"
                ) from exc

        del session_artifacts
