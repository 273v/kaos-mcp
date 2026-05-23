from __future__ import annotations

import asyncio
from typing import Any

from kaos_core import KaosContext, KaosRuntime, Root
from mcp.server.fastmcp import Context as FastMCPContext

from kaos_mcp.config import KaosMCPSettings


def caller_session_id(ctx: FastMCPContext) -> str | None:
    """Return the caller's session identity for artifact isolation.

    Resolution order (audit-04 F-001 security hardening):

    1. ``ctx.client_id`` — populated when the request supplies
       ``_meta.client_id`` explicitly. Highest precedence; lets a
       trusted broker re-tag requests on behalf of multiple end users
       and is the canonical production identity.
    2. ``ctx.request_id`` — per-request UUID. Last-ditch fallback;
       means every request is its own session, so cross-request reads
       always fail. Safe-by-default when no identity is presented.

    Returns ``None`` when none of the above are available — typically
    when the handler is invoked outside an MCP request scope (in-process
    / test callers). Per the artifact store contract, ``None`` means
    "trusted in-process caller, no enforcement". Real MCP traffic always
    has a request scope so production callers never hit this fallback.

    The previous ``ctx.session.client_params.clientInfo.name`` fallback
    was removed in audit-04 (F-001) because ``clientInfo.name`` is a
    client *product* name, not a tenant / session id. Two concurrent
    streamable-HTTP clients both reporting ``"claude-code"`` collapsed
    to the same isolation key, violating the per-session-isolation
    guarantee in SECURITY.md. Callers that need cross-request artifact
    reads MUST supply ``_meta.client_id`` explicitly; HTTP deployments
    need authenticated transport (mTLS, OAuth, signed JWT) in front
    that injects this identity.
    """
    try:
        client_id = ctx.client_id
    except (ValueError, AttributeError):
        client_id = None
    if client_id:
        return client_id

    try:
        request_id = ctx.request_id
    except (ValueError, AttributeError):
        return None
    return request_id or None


class ContextBridge:
    def __init__(self, runtime: KaosRuntime, settings: KaosMCPSettings) -> None:
        self._runtime = runtime
        self._settings = settings

    async def list_roots(self, context: FastMCPContext) -> list[Root] | None:
        try:
            session = context.session
        except ValueError:
            return None
        if not hasattr(session, "list_roots") or not callable(session.list_roots):
            return None
        try:
            result = await asyncio.wait_for(
                session.list_roots(), timeout=self._settings.list_roots_timeout
            )
        except (TimeoutError, Exception):
            return None
        return [Root(uri=str(root.uri), name=root.name) for root in result.roots]

    async def create_kaos_context(self, context: FastMCPContext) -> KaosContext:
        request_meta = getattr(context.request_context, "meta", None)
        metadata: dict[str, Any] = {
            "client_id": context.client_id,
            "request_id": context.request_id,
            "transport": self._settings.transport,
        }

        progress_token = getattr(request_meta, "progressToken", None)
        if progress_token is not None:
            metadata["progress_token"] = progress_token

        # Extract per-request config overrides from _meta.kaos_config
        config_overrides: dict[str, Any] | None = None
        if request_meta is not None:
            # request_meta could be a dict or an object with attributes
            if isinstance(request_meta, dict):
                raw_config = request_meta.get("kaos_config")
            else:
                raw_config = getattr(request_meta, "kaos_config", None)
            if isinstance(raw_config, dict):
                config_overrides = raw_config

        kaos_context = KaosContext.create(
            session_id=context.client_id or context.request_id,
            trace_id=context.request_id,
            metadata=metadata,
            roots=await self.list_roots(context),
            runtime=self._runtime,
            config=config_overrides,
        )
        kaos_context.set_progress_callback(
            lambda progress, total, message: context.report_progress(progress, total, message)
        )
        return kaos_context
