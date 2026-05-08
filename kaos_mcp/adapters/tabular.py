"""MCP resource templates for TabularDocument artifacts.

Peer to ContentResourceAdapter. Registers URI templates that let agents
navigate tabular data by table, column, schema, and row range.

Templates:
    kaos://tabular/{artifact_id}                              → full JSON AST
    kaos://tabular/{artifact_id}/summary                      → table list + dimensions
    kaos://tabular/{artifact_id}/markdown                     → full document as markdown
    kaos://tabular/{artifact_id}/table/{name}                 → single table as TSV
    kaos://tabular/{artifact_id}/table/{name}/schema          → column schema
    kaos://tabular/{artifact_id}/table/{name}/describe        → column stats
    kaos://tabular/{artifact_id}/table/{name}/markdown        → single table as markdown
    kaos://tabular/{artifact_id}/table/{name}/rows/{start}/{count} → row range as TSV
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from mcp.server.fastmcp import Context as FastMCPContext

from kaos_mcp.adapters._error_handling import resource_error_from_exception
from kaos_mcp.adapters.context import ContextBridge, caller_session_id

if TYPE_CHECKING:
    from kaos_core.registry.container import KaosRuntime
    from mcp.server.fastmcp import FastMCP

    from kaos_mcp.config import KaosMCPSettings

TABULAR_TEMPLATE_COUNT = 8


class TabularResourceAdapter:
    """Registers MCP resource templates for TabularDocument artifacts."""

    def __init__(
        self,
        runtime: KaosRuntime,
        settings: KaosMCPSettings | None = None,
    ) -> None:
        self._runtime = runtime
        if settings is None:
            from kaos_mcp.config import KaosMCPSettings

            settings = KaosMCPSettings()
        self._settings = settings
        self._bridge = ContextBridge(runtime, self._settings)

    def register_tabular_templates(self, app: FastMCP) -> int:
        """Register tabular document resource templates. Returns count."""
        self._register_templates(app)
        return TABULAR_TEMPLATE_COUNT

    def _assert_caller_can_read(self, artifact_id: str, ctx: FastMCPContext) -> str | None:
        """Refuse cross-session reads at the boundary (audit-02 F1).

        Returns ``None`` when no MCP request is active (in-process / test
        callers); enforcement bypassed in that case per the trusted-in-
        process contract documented in ``ArtifactStore``.
        """
        caller = caller_session_id(ctx)
        self._runtime.artifacts.resolve(artifact_id, caller_session_id=caller)
        return caller

    def _register_templates(self, app: FastMCP) -> None:
        runtime = self._runtime

        # 1. Full JSON AST
        @app.resource(
            "kaos://tabular/{artifact_id}",
            name="tabular-document",
            title="Tabular Document (JSON)",
            description="Full TabularDocument AST as JSON.",
            mime_type="application/json",
        )
        async def tabular_json(artifact_id: str, ctx: FastMCPContext) -> str:
            try:
                caller = self._assert_caller_can_read(artifact_id, ctx)
                # F4: bound the read at max_resource_bytes — read_body raises
                # ``Artifact exceeds inline read limit`` for oversize artifacts.
                payload = await runtime.artifacts.read_body(
                    artifact_id,
                    max_bytes=self._settings.max_resource_bytes,
                    caller_session_id=caller,
                )
                return payload.decode("utf-8")
            except Exception as exc:
                raise resource_error_from_exception(exc) from exc

        # 2. Summary (table list + dimensions + column types)
        @app.resource(
            "kaos://tabular/{artifact_id}/summary",
            name="tabular-summary",
            title="Tabular Summary",
            description="Table names, dimensions, and column types.",
            mime_type="application/json",
        )
        async def tabular_summary(artifact_id: str, ctx: FastMCPContext) -> str:
            try:
                self._assert_caller_can_read(artifact_id, ctx)
                from kaos_content.artifacts import load_tabular
                from kaos_content.views.tabular_view import TabularView

                doc = await load_tabular(
                    artifact_id, runtime, max_bytes=self._settings.max_resource_bytes
                )
                view = TabularView(doc)
                return json.dumps(view.summary_dict(), indent=2, default=str)
            except Exception as exc:
                raise resource_error_from_exception(exc) from exc

        # 3. Full document as markdown
        @app.resource(
            "kaos://tabular/{artifact_id}/markdown",
            name="tabular-markdown",
            title="Tabular Document (Markdown)",
            description="Full tabular document as markdown with tables.",
            mime_type="text/markdown",
        )
        async def tabular_markdown(artifact_id: str, ctx: FastMCPContext) -> str:
            try:
                self._assert_caller_can_read(artifact_id, ctx)
                from kaos_content.artifacts import load_tabular
                from kaos_content.serializers.tabular import serialize_tabular_markdown

                doc = await load_tabular(
                    artifact_id, runtime, max_bytes=self._settings.max_resource_bytes
                )
                return serialize_tabular_markdown(doc)
            except Exception as exc:
                raise resource_error_from_exception(exc) from exc

        # 4. Single table as TSV
        @app.resource(
            "kaos://tabular/{artifact_id}/table/{table_name}",
            name="tabular-table-tsv",
            title="Table (TSV)",
            description="Single table as TSV. Token-efficient format for agents.",
            mime_type="text/tab-separated-values",
        )
        async def tabular_table_tsv(artifact_id: str, table_name: str, ctx: FastMCPContext) -> str:
            try:
                self._assert_caller_can_read(artifact_id, ctx)
                from urllib.parse import unquote

                from kaos_content.artifacts import load_tabular
                from kaos_content.serializers.tabular import serialize_tsv

                doc = await load_tabular(
                    artifact_id, runtime, max_bytes=self._settings.max_resource_bytes
                )
                table = doc.get_table(unquote(table_name))
                return serialize_tsv(table)
            except Exception as exc:
                raise resource_error_from_exception(exc) from exc

        # 5. Table schema (column names, types, nullability)
        @app.resource(
            "kaos://tabular/{artifact_id}/table/{table_name}/schema",
            name="tabular-table-schema",
            title="Table Schema",
            description="Column names, types, nullability, and metadata.",
            mime_type="application/json",
        )
        async def tabular_table_schema(
            artifact_id: str, table_name: str, ctx: FastMCPContext
        ) -> str:
            try:
                self._assert_caller_can_read(artifact_id, ctx)
                from urllib.parse import unquote

                from kaos_content.artifacts import load_tabular
                from kaos_content.views.tabular_view import TabularView

                doc = await load_tabular(
                    artifact_id, runtime, max_bytes=self._settings.max_resource_bytes
                )
                view = TabularView(doc)
                schema = view.table_schema(unquote(table_name))
                return json.dumps(schema, indent=2, default=str)
            except Exception as exc:
                raise resource_error_from_exception(exc) from exc

        # 6. Table describe (column-level stats)
        @app.resource(
            "kaos://tabular/{artifact_id}/table/{table_name}/describe",
            name="tabular-table-describe",
            title="Table Description",
            description="Column statistics: null counts, unique counts, min/max, samples.",
            mime_type="application/json",
        )
        async def tabular_table_describe(
            artifact_id: str, table_name: str, ctx: FastMCPContext
        ) -> str:
            try:
                self._assert_caller_can_read(artifact_id, ctx)
                from dataclasses import asdict
                from urllib.parse import unquote

                from kaos_content.artifacts import load_tabular
                from kaos_content.views.tabular_view import TabularView

                doc = await load_tabular(
                    artifact_id, runtime, max_bytes=self._settings.max_resource_bytes
                )
                view = TabularView(doc)
                stats = view.all_column_stats(unquote(table_name))
                return json.dumps([asdict(s) for s in stats], indent=2, default=str)
            except Exception as exc:
                raise resource_error_from_exception(exc) from exc

        # 7. Table as markdown
        @app.resource(
            "kaos://tabular/{artifact_id}/table/{table_name}/markdown",
            name="tabular-table-markdown",
            title="Table (Markdown)",
            description="Single table as a markdown table.",
            mime_type="text/markdown",
        )
        async def tabular_table_md(artifact_id: str, table_name: str, ctx: FastMCPContext) -> str:
            try:
                self._assert_caller_can_read(artifact_id, ctx)
                from urllib.parse import unquote

                from kaos_content.artifacts import load_tabular
                from kaos_content.serializers.tabular import serialize_markdown_table

                doc = await load_tabular(
                    artifact_id, runtime, max_bytes=self._settings.max_resource_bytes
                )
                table = doc.get_table(unquote(table_name))
                return serialize_markdown_table(table)
            except Exception as exc:
                raise resource_error_from_exception(exc) from exc

        # 8. Row range as TSV
        @app.resource(
            "kaos://tabular/{artifact_id}/table/{table_name}/rows/{start}/{count}",
            name="tabular-table-rows",
            title="Table Row Range (TSV)",
            description="Specific row range as TSV. 0-based start index.",
            mime_type="text/tab-separated-values",
        )
        async def tabular_table_rows(
            artifact_id: str,
            table_name: str,
            start: str,
            count: str,
            ctx: FastMCPContext,
        ) -> str:
            try:
                self._assert_caller_can_read(artifact_id, ctx)
                from urllib.parse import unquote

                from kaos_content.artifacts import load_tabular
                from kaos_content.serializers.tabular import serialize_tsv
                from kaos_content.views.tabular_view import TabularView

                s = int(start)
                n = int(count)
                # F4: cap caller-supplied row count.
                if n > self._settings.max_table_rows:
                    raise resource_error_from_exception(
                        ValueError(
                            f"count {n} exceeds max_table_rows {self._settings.max_table_rows}"
                        ),
                        context=(
                            f"kaos://tabular/{artifact_id}/table/{table_name}/rows/{start}/{count}"
                        ),
                    )

                doc = await load_tabular(
                    artifact_id, runtime, max_bytes=self._settings.max_resource_bytes
                )
                view = TabularView(doc)
                sliced = view.table_slice(unquote(table_name), s, s + n)
                return serialize_tsv(sliced)
            except Exception as exc:
                raise resource_error_from_exception(exc) from exc

        # Clean up closure references
        del (
            tabular_json,
            tabular_summary,
            tabular_markdown,
            tabular_table_tsv,
            tabular_table_schema,
            tabular_table_describe,
            tabular_table_md,
            tabular_table_rows,
        )
