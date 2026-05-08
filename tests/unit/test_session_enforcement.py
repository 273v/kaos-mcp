"""Regression tests for audit-02 F1: cross-session artifact isolation.

Validates that ``caller_session_id`` derives the caller's identity from
``ctx.client_id`` (with ``request_id`` fallback) and that adapter helpers
refuse to read artifacts owned by a different session — uniform with
the "Unknown artifact" error so probing cannot enumerate other
sessions.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from kaos_core import KaosContext, KaosRuntime
from kaos_core.exceptions import ResourceError
from mcp.server.fastmcp.exceptions import ResourceError as FastMCPResourceError

from kaos_mcp.adapters.content import ContentResourceAdapter
from kaos_mcp.adapters.context import caller_session_id
from kaos_mcp.adapters.tabular import TabularResourceAdapter


def _make_ctx(
    *,
    client_id: str | None = None,
    request_id: str | None = None,
    client_info_name: str | None = None,
) -> MagicMock:
    """Mock FastMCPContext with attribute-style ``client_id``, ``request_id``,
    and a ``session.client_params.clientInfo.name`` chain (audit-02 F1's
    second-priority fallback). When ``client_info_name`` is None we set
    ``client_params=None`` so the chain returns None and resolution falls
    through to ``request_id``."""
    ctx = MagicMock()
    ctx.client_id = client_id
    ctx.request_id = request_id
    if client_info_name is None:
        ctx.session.client_params = None
    else:
        ctx.session.client_params.clientInfo.name = client_info_name
    return ctx


def _make_failing_ctx() -> MagicMock:
    """Mock context where every identity source raises outside-of-request."""
    ctx = MagicMock()
    type(ctx).client_id = property(
        lambda _self: (_ for _ in ()).throw(
            ValueError("Context is not available outside of a request")
        )
    )
    type(ctx).session = property(
        lambda _self: (_ for _ in ()).throw(
            ValueError("Context is not available outside of a request")
        )
    )
    type(ctx).request_id = property(
        lambda _self: (_ for _ in ()).throw(
            ValueError("Context is not available outside of a request")
        )
    )
    return ctx


class TestCallerSessionId:
    def test_returns_client_id_when_set(self) -> None:
        ctx = _make_ctx(client_id="client-A", request_id="req-123")
        assert caller_session_id(ctx) == "client-A"

    def test_falls_back_to_clientinfo_name(self) -> None:
        # Second-priority fallback: session-stable clientInfo.name from MCP
        # initialize. Same identity across every request in one session.
        ctx = _make_ctx(client_id=None, client_info_name="claude-code", request_id="req-789")
        assert caller_session_id(ctx) == "claude-code"

    def test_falls_back_to_request_id(self) -> None:
        ctx = _make_ctx(client_id=None, request_id="req-456")
        assert caller_session_id(ctx) == "req-456"

    def test_returns_none_when_all_missing(self) -> None:
        ctx = _make_ctx(client_id=None, request_id=None)
        assert caller_session_id(ctx) is None

    def test_returns_none_when_context_raises(self) -> None:
        # FastMCP raises ValueError outside a request; helper must not propagate.
        ctx = _make_failing_ctx()
        assert caller_session_id(ctx) is None


class TestArtifactStoreCrossSessionDenial:
    """Direct kaos-core checks — proves enforcement is live end-to-end."""

    @pytest.mark.unit
    async def test_resolve_denies_cross_session(self, runtime: KaosRuntime) -> None:
        ctx_obj = KaosContext.create(session_id="owner-session", runtime=runtime)
        await ctx_obj.get_vfs_path("artifacts/secret.txt").write_text("secret")
        manifest = await runtime.artifacts.create_from_path(
            "artifacts/secret.txt",
            context_id="owner-session",
            session_id="owner-session",
            name="secret",
            mime_type="text/plain",
        )

        # Owner: passes
        runtime.artifacts.resolve(manifest.artifact_id, caller_session_id="owner-session")

        # Foreign caller: uniform "Unknown artifact" — never reveal existence.
        with pytest.raises(ResourceError, match="Unknown artifact"):
            runtime.artifacts.resolve(manifest.artifact_id, caller_session_id="attacker-session")

        # No caller (in-process trusted): passes through.
        runtime.artifacts.resolve(manifest.artifact_id, caller_session_id=None)

    @pytest.mark.unit
    async def test_read_text_denies_cross_session(self, runtime: KaosRuntime) -> None:
        ctx_obj = KaosContext.create(session_id="owner-session", runtime=runtime)
        await ctx_obj.get_vfs_path("artifacts/body.txt").write_text("payload")
        manifest = await runtime.artifacts.create_from_path(
            "artifacts/body.txt",
            context_id="owner-session",
            session_id="owner-session",
            name="body",
            mime_type="text/plain",
        )

        with pytest.raises(ResourceError, match="Unknown artifact"):
            await runtime.artifacts.read_text(
                manifest.artifact_id, caller_session_id="attacker-session"
            )


class TestContentAdapterCrossSessionDenial:
    @pytest.mark.unit
    async def test_assert_caller_can_read_denies_foreign_session(
        self, runtime: KaosRuntime
    ) -> None:
        ctx_obj = KaosContext.create(session_id="owner", runtime=runtime)
        await ctx_obj.get_vfs_path("artifacts/doc.json").write_text('{"hello":1}')
        manifest = await runtime.artifacts.create_from_path(
            "artifacts/doc.json",
            context_id="owner",
            session_id="owner",
            name="doc",
            mime_type="application/json",
        )

        adapter = ContentResourceAdapter(runtime)
        # Foreign caller — must raise uniform "Unknown artifact"
        attacker_ctx = _make_ctx(client_id="attacker", request_id=None)
        with pytest.raises(ResourceError, match="Unknown artifact"):
            adapter._assert_caller_can_read(manifest.artifact_id, attacker_ctx)

        # Owner caller — must pass.
        owner_ctx = _make_ctx(client_id="owner", request_id=None)
        assert adapter._assert_caller_can_read(manifest.artifact_id, owner_ctx) == "owner"


class TestTabularAdapterCrossSessionDenial:
    @pytest.mark.unit
    async def test_assert_caller_can_read_denies_foreign_session(
        self, runtime: KaosRuntime
    ) -> None:
        ctx_obj = KaosContext.create(session_id="owner", runtime=runtime)
        await ctx_obj.get_vfs_path("artifacts/tab.json").write_text('{"hello":1}')
        manifest = await runtime.artifacts.create_from_path(
            "artifacts/tab.json",
            context_id="owner",
            session_id="owner",
            name="tab",
            mime_type="application/json",
        )

        adapter = TabularResourceAdapter(runtime)
        attacker_ctx = _make_ctx(client_id="attacker", request_id=None)
        with pytest.raises(ResourceError, match="Unknown artifact"):
            adapter._assert_caller_can_read(manifest.artifact_id, attacker_ctx)

        owner_ctx = _make_ctx(client_id="owner", request_id=None)
        assert adapter._assert_caller_can_read(manifest.artifact_id, owner_ctx) == "owner"


class TestSessionArtifactsCallerMismatch:
    """Reach into the registered handler to verify URI ↔ caller mismatch."""

    @pytest.mark.unit
    async def test_uri_session_other_than_caller_raises(self, runtime: KaosRuntime) -> None:
        from collections.abc import Awaitable, Callable
        from typing import Any, cast

        from kaos_mcp.adapters import session as session_module

        # Capture the handler at registration time by registering our own app
        # mock and recording the decorated function.
        captured: dict[str, Any] = {}

        class _RecordingApp:
            def resource(self, uri: str, **_kw: object):
                def decorator(fn: Callable[..., Awaitable[str]]) -> Callable[..., Awaitable[str]]:
                    captured["fn"] = fn
                    captured["uri"] = uri
                    return fn

                return decorator

        adapter = session_module.SessionResourceAdapter(runtime)
        adapter._register_templates(cast(Any, _RecordingApp()))
        handler = cast(Callable[[str, Any], Awaitable[str]], captured["fn"])

        # Caller = "alpha", URI session_id = "beta" → uniform Unknown session.
        attacker_ctx = _make_ctx(client_id="alpha", request_id=None)
        with pytest.raises(FastMCPResourceError, match="Unknown session"):
            await handler("beta", attacker_ctx)

        # Caller = "alpha", URI session_id = "alpha" → succeeds (empty list ok).
        same_ctx = _make_ctx(client_id="alpha", request_id=None)
        result = await handler("alpha", same_ctx)
        assert isinstance(result, str)
