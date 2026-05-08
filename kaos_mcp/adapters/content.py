"""Content document resource templates for MCP.

Exposes ContentDocument artifacts as structured MCP resources:
  - kaos://content/{artifact_id}              → full JSON AST
  - kaos://content/{artifact_id}/markdown     → serialized markdown
  - kaos://content/{artifact_id}/metadata     → document metadata
  - kaos://content/{artifact_id}/outline      → heading hierarchy
  - kaos://content/{artifact_id}/tables       → table summaries
  - kaos://content/{artifact_id}/annotations  → all annotations
  - kaos://content/{artifact_id}/definitions  → link definitions
  - kaos://content/{artifact_id}/node/{ref}   → subtree by ref
"""

from __future__ import annotations

import json

from kaos_core import KaosRuntime
from mcp.server.fastmcp import Context as FastMCPContext
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ResourceError as FastMCPResourceError

from kaos_mcp.adapters._error_handling import resource_error_from_exception
from kaos_mcp.adapters.context import ContextBridge
from kaos_mcp.config import KaosMCPSettings

# Number of content resource templates registered
CONTENT_TEMPLATE_COUNT = 12


class ContentResourceAdapter:
    """Registers MCP resource templates for ContentDocument artifacts."""

    def __init__(self, runtime: KaosRuntime, settings: KaosMCPSettings | None = None) -> None:
        self._runtime = runtime
        self._settings = settings or KaosMCPSettings()
        self._bridge = ContextBridge(runtime, self._settings)

    def register_content_templates(self, app: FastMCP) -> int:
        """Register content document resource templates. Returns count."""
        self._register_templates(app)
        return CONTENT_TEMPLATE_COUNT

    def _load_document(self, artifact_id: str) -> tuple:
        """Load a ContentDocument from an artifact. Returns (document, manifest)."""

        manifest = self._runtime.artifacts.resolve(artifact_id)
        # Verify it's a JSON content document
        if manifest.mime_type not in ("application/json", None):
            msg = f"Artifact {artifact_id} is not a JSON document (mime: {manifest.mime_type})"
            raise FastMCPResourceError(msg)
        return manifest, None  # Lazy — we load async in each handler

    def _register_templates(self, app: FastMCP) -> None:
        @app.resource(
            "kaos://content/{artifact_id}",
            name="content-document",
            title="Content Document (JSON)",
            description="Full ContentDocument AST as JSON.",
            mime_type="application/json",
        )
        async def content_document(artifact_id: str, ctx: FastMCPContext) -> str:
            try:
                return await self._runtime.artifacts.read_text(artifact_id)
            except Exception as exc:
                raise resource_error_from_exception(exc) from exc

        @app.resource(
            "kaos://content/{artifact_id}/markdown",
            name="content-markdown",
            title="Content Document (Markdown)",
            description="ContentDocument rendered as markdown.",
            mime_type="text/markdown",
        )
        async def content_markdown(artifact_id: str, ctx: FastMCPContext) -> str:
            try:
                from kaos_content.artifacts import load_document
                from kaos_content.serializers import serialize_markdown

                doc = await load_document(artifact_id, self._runtime)
                return serialize_markdown(doc)
            except Exception as exc:
                raise resource_error_from_exception(exc) from exc

        @app.resource(
            "kaos://content/{artifact_id}/metadata",
            name="content-metadata",
            title="Document Metadata",
            description="Document-level metadata (title, authors, etc.).",
            mime_type="application/json",
        )
        async def content_metadata(artifact_id: str, ctx: FastMCPContext) -> str:
            try:
                from kaos_content.artifacts import document_metadata, load_document

                doc = await load_document(artifact_id, self._runtime)
                return json.dumps(document_metadata(doc), indent=2)
            except Exception as exc:
                raise resource_error_from_exception(exc) from exc

        @app.resource(
            "kaos://content/{artifact_id}/outline",
            name="content-outline",
            title="Document Outline",
            description="Heading hierarchy with depths and refs.",
            mime_type="application/json",
        )
        async def content_outline(artifact_id: str, ctx: FastMCPContext) -> str:
            try:
                from kaos_content.artifacts import document_outline, load_document

                doc = await load_document(artifact_id, self._runtime)
                return json.dumps(document_outline(doc), indent=2)
            except Exception as exc:
                raise resource_error_from_exception(exc) from exc

        @app.resource(
            "kaos://content/{artifact_id}/tables",
            name="content-tables",
            title="Document Tables",
            description="Table summaries with row/col counts.",
            mime_type="application/json",
        )
        async def content_tables(artifact_id: str, ctx: FastMCPContext) -> str:
            try:
                from kaos_content.artifacts import document_tables_summary, load_document

                doc = await load_document(artifact_id, self._runtime)
                return json.dumps(document_tables_summary(doc), indent=2)
            except Exception as exc:
                raise resource_error_from_exception(exc) from exc

        @app.resource(
            "kaos://content/{artifact_id}/annotations",
            name="content-annotations",
            title="Document Annotations",
            description="All annotations with types and targets.",
            mime_type="application/json",
        )
        async def content_annotations(artifact_id: str, ctx: FastMCPContext) -> str:
            try:
                from kaos_content.artifacts import document_annotations_by_type, load_document

                doc = await load_document(artifact_id, self._runtime)
                return json.dumps(document_annotations_by_type(doc), indent=2)
            except Exception as exc:
                raise resource_error_from_exception(exc) from exc

        @app.resource(
            "kaos://content/{artifact_id}/definitions",
            name="content-definitions",
            title="Document Definitions",
            description="Link/reference definitions from the document.",
            mime_type="application/json",
        )
        async def content_definitions(artifact_id: str, ctx: FastMCPContext) -> str:
            try:
                from kaos_content.artifacts import document_definitions, load_document

                doc = await load_document(artifact_id, self._runtime)
                return json.dumps(document_definitions(doc), indent=2)
            except Exception as exc:
                raise resource_error_from_exception(exc) from exc

        @app.resource(
            "kaos://content/{artifact_id}/node/{node_ref}",
            name="content-node",
            title="Document Node",
            description=(
                "Single AST node subtree by body index "
                "(e.g., node_ref='body/0' → first body block)."
            ),
            mime_type="application/json",
        )
        async def content_node(artifact_id: str, node_ref: str, ctx: FastMCPContext) -> str:
            try:
                from urllib.parse import unquote

                from kaos_content.artifacts import document_node_subtree, load_document

                doc = await load_document(artifact_id, self._runtime)
                # URL-decode and reconstruct the JSON pointer format
                decoded = unquote(node_ref)
                ref = f"#/{decoded}" if not decoded.startswith("#") else decoded
                return json.dumps(document_node_subtree(doc, ref), indent=2)
            except Exception as exc:
                raise resource_error_from_exception(exc) from exc

        # ── Page/section navigation resources ──

        @app.resource(
            "kaos://content/{artifact_id}/pages",
            name="content-pages-index",
            title="Document Pages Index",
            description="Page index with page numbers and block counts.",
            mime_type="application/json",
        )
        async def content_pages_index(artifact_id: str, ctx: FastMCPContext) -> str:
            try:
                from kaos_content.artifacts import load_document
                from kaos_content.views import DocumentView

                doc = await load_document(artifact_id, self._runtime)
                view = DocumentView(doc)
                pages = [
                    {
                        "page_number": p.page_number,
                        "block_count": len(p.blocks),
                        "section_refs": list(p.section_refs),
                    }
                    for p in view.pages
                ]
                return json.dumps(pages, indent=2)
            except Exception as exc:
                raise resource_error_from_exception(exc) from exc

        @app.resource(
            "kaos://content/{artifact_id}/pages/{page_number}",
            name="content-page",
            title="Document Page (Markdown)",
            description="Single page content rendered as markdown.",
            mime_type="text/markdown",
        )
        async def content_page(artifact_id: str, page_number: str, ctx: FastMCPContext) -> str:
            try:
                from kaos_content.artifacts import load_document
                from kaos_content.views import DocumentView

                doc = await load_document(artifact_id, self._runtime)
                view = DocumentView(doc)
                return view.page_as_markdown(int(page_number))
            except Exception as exc:
                raise resource_error_from_exception(exc) from exc

        @app.resource(
            "kaos://content/{artifact_id}/sections",
            name="content-sections-tree",
            title="Document Sections Tree",
            description="Recursive section tree with heading text, depth, and page ranges.",
            mime_type="application/json",
        )
        async def content_sections_tree(artifact_id: str, ctx: FastMCPContext) -> str:
            try:
                from kaos_content.artifacts import load_document
                from kaos_content.views import DocumentView

                doc = await load_document(artifact_id, self._runtime)
                view = DocumentView(doc)

                def _section_to_dict(sv):
                    d = {
                        "heading_ref": sv.heading_ref,
                        "heading_text": sv.heading_text,
                        "depth": sv.depth,
                        "block_count": len(sv.blocks),
                        "page_range": list(sv.page_range) if sv.page_range else None,
                    }
                    if sv.subsections:
                        d["subsections"] = [_section_to_dict(s) for s in sv.subsections]
                    return d

                sections = [_section_to_dict(s) for s in view.sections]
                return json.dumps(sections, indent=2)
            except Exception as exc:
                raise resource_error_from_exception(exc) from exc

        @app.resource(
            "kaos://content/{artifact_id}/sections/{section_ref}",
            name="content-section",
            title="Document Section (Markdown)",
            description="Single section content rendered as markdown.",
            mime_type="text/markdown",
        )
        async def content_section(artifact_id: str, section_ref: str, ctx: FastMCPContext) -> str:
            try:
                from urllib.parse import unquote

                from kaos_content.artifacts import load_document
                from kaos_content.views import DocumentView

                doc = await load_document(artifact_id, self._runtime)
                view = DocumentView(doc)
                decoded = unquote(section_ref)
                ref = f"#/{decoded}" if not decoded.startswith("#") else decoded
                return view.section_as_markdown(ref)
            except Exception as exc:
                raise resource_error_from_exception(exc) from exc

        # Clean up local names from module scope
        del (
            content_document,
            content_markdown,
            content_metadata,
            content_outline,
            content_tables,
            content_annotations,
            content_definitions,
            content_node,
            content_pages_index,
            content_page,
            content_sections_tree,
            content_section,
        )
