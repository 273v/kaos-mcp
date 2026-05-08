"""End-to-end integration test: content document pipeline through MCP.

Proves the full pipeline:
  1. Parse markdown → ContentDocument
  2. Store as artifact via kaos-content helpers
  3. Expose via kaos-mcp content resource templates
  4. Read back via in-memory MCP client session
  5. Validate round-trip fidelity and resource correctness
"""

from __future__ import annotations

import json

import pytest
from kaos_content import DocumentBuilder, parse_markdown
from kaos_content.artifacts import (
    document_to_summary,
    load_document,
    store_document,
)
from kaos_core import KaosContext, KaosRuntime, KaosSettings
from kaos_core.types.enums import StorageBackend
from kaos_core.vfs import VFSConfig, VirtualFileSystem
from mcp import types
from mcp.shared.memory import create_connected_server_and_client_session
from pydantic import AnyUrl

from kaos_mcp import create_app

SAMPLE_MARKDOWN = """\
---
title: Quarterly Report Q1 2026
---

# Executive Summary

Revenue grew 15% year-over-year to $12.3M.

## Key Metrics

| Metric | Q1 2025 | Q1 2026 | Change |
|--------|---------|---------|--------|
| Revenue | $10.7M | $12.3M | +15% |
| Users | 8,200 | 12,400 | +51% |
| NPS | 42 | 58 | +16 |

## Highlights

- Launched v2.0 of the platform
- Expanded to 3 new markets
- Reduced churn by 22%

# Financial Details

## Revenue Breakdown

Enterprise accounts contributed 72% of total revenue.

## Cost Structure

Operating expenses increased 8%, below revenue growth rate.

# Outlook

We expect Q2 revenue of $13.5M based on current pipeline.
"""


def _make_runtime(tmp_path) -> KaosRuntime:
    settings = KaosSettings(
        artifact_inline_read_max_bytes=262_144,
        artifact_chunk_size_bytes=65_536,
    )
    runtime = KaosRuntime(config=settings)
    runtime.vfs = VirtualFileSystem(
        VFSConfig(default_backend=StorageBackend.DISK, disk_base_path=tmp_path / "vfs")
    )
    runtime.artifacts = runtime.artifacts.__class__(
        runtime.vfs,
        manifest_context_id=settings.artifact_manifest_context_id,
        manifest_prefix=settings.artifact_manifest_prefix,
        max_inline_read_bytes=settings.artifact_inline_read_max_bytes,
        default_chunk_size=settings.artifact_chunk_size_bytes,
        temporary_ttl_seconds=settings.artifact_temporary_ttl_seconds,
    )
    return runtime


@pytest.mark.integration
async def test_full_content_pipeline_through_mcp(tmp_path) -> None:
    """Parse → store → expose via MCP → read back → validate."""
    runtime = _make_runtime(tmp_path)
    context = KaosContext.create(session_id="pipeline-test", runtime=runtime)

    # 1. Parse markdown into ContentDocument
    doc = parse_markdown(SAMPLE_MARKDOWN)
    assert doc.metadata.title == "Quarterly Report Q1 2026"

    # 2. Store as artifact
    manifest = await store_document(doc, runtime, context, name="q1-report")
    assert manifest.mime_type == "application/json"
    assert manifest.size > 0

    # 3. Verify we can load it back
    loaded = await load_document(manifest.artifact_id, runtime)
    assert loaded.metadata.title == doc.metadata.title
    assert len(loaded.body) == len(doc.body)

    # 4. Create MCP app and read resources via in-memory session
    app = create_app(runtime)

    async with create_connected_server_and_client_session(app) as session:
        # List resource templates
        templates_result = await session.list_resource_templates()
        template_uris = {t.uriTemplate for t in templates_result.resourceTemplates}
        assert "kaos://content/{artifact_id}" in template_uris
        assert "kaos://content/{artifact_id}/markdown" in template_uris
        assert "kaos://content/{artifact_id}/metadata" in template_uris
        assert "kaos://content/{artifact_id}/outline" in template_uris

        # Read full JSON document
        json_result = await session.read_resource(AnyUrl(f"kaos://content/{manifest.artifact_id}"))
        json_text = json_result.contents[0]
        assert isinstance(json_text, types.TextResourceContents)
        parsed_back = json.loads(json_text.text)
        assert parsed_back["metadata"]["title"] == "Quarterly Report Q1 2026"

        # Read markdown view
        md_result = await session.read_resource(
            AnyUrl(f"kaos://content/{manifest.artifact_id}/markdown")
        )
        md_text = md_result.contents[0]
        assert isinstance(md_text, types.TextResourceContents)
        assert "Executive Summary" in md_text.text
        assert "Revenue grew" in md_text.text

        # Read metadata
        meta_result = await session.read_resource(
            AnyUrl(f"kaos://content/{manifest.artifact_id}/metadata")
        )
        meta_text = meta_result.contents[0]
        assert isinstance(meta_text, types.TextResourceContents)
        meta_dict = json.loads(meta_text.text)
        assert meta_dict["title"] == "Quarterly Report Q1 2026"

        # Read outline
        outline_result = await session.read_resource(
            AnyUrl(f"kaos://content/{manifest.artifact_id}/outline")
        )
        outline_text = outline_result.contents[0]
        assert isinstance(outline_text, types.TextResourceContents)
        outline = json.loads(outline_text.text)
        assert len(outline) >= 5  # At least 5 headings
        assert any(h["text"] == "Executive Summary" for h in outline)
        assert any(h["depth"] == 2 for h in outline)

        # Read tables
        tables_result = await session.read_resource(
            AnyUrl(f"kaos://content/{manifest.artifact_id}/tables")
        )
        tables_text = tables_result.contents[0]
        assert isinstance(tables_text, types.TextResourceContents)
        tables = json.loads(tables_text.text)
        assert len(tables) >= 1
        assert tables[0]["rows"] >= 2  # header + data rows
        assert tables[0]["cols"] >= 2

        # Read annotations (empty for this doc)
        ann_result = await session.read_resource(
            AnyUrl(f"kaos://content/{manifest.artifact_id}/annotations")
        )
        ann_text = ann_result.contents[0]
        assert isinstance(ann_text, types.TextResourceContents)
        assert json.loads(ann_text.text) == []

        # Read definitions (empty for this doc)
        defs_result = await session.read_resource(
            AnyUrl(f"kaos://content/{manifest.artifact_id}/definitions")
        )
        defs_text = defs_result.contents[0]
        assert isinstance(defs_text, types.TextResourceContents)
        assert json.loads(defs_text.text) == {}


@pytest.mark.integration
async def test_content_node_resource(tmp_path) -> None:
    """Access individual nodes via MCP resource template."""
    runtime = _make_runtime(tmp_path)
    context = KaosContext.create(session_id="node-test", runtime=runtime)

    doc = parse_markdown(SAMPLE_MARKDOWN)
    manifest = await store_document(doc, runtime, context, name="node-doc")
    app = create_app(runtime)

    async with create_connected_server_and_client_session(app) as session:
        # Read first body node (should be heading "Executive Summary")
        node_result = await session.read_resource(
            AnyUrl(f"kaos://content/{manifest.artifact_id}/node/body%2F0")
        )
        node_text = node_result.contents[0]
        assert isinstance(node_text, types.TextResourceContents)
        node_dict = json.loads(node_text.text)
        assert node_dict["node_type"] == "heading"


@pytest.mark.integration
async def test_tool_result_with_content_artifact(tmp_path) -> None:
    """Verify ArtifactManifest.to_tool_result works with content documents."""
    runtime = _make_runtime(tmp_path)
    context = KaosContext.create(session_id="tool-result-test", runtime=runtime)

    doc = parse_markdown(SAMPLE_MARKDOWN)
    manifest = await store_document(doc, runtime, context, name="tool-doc")
    summary = document_to_summary(doc, max_length=200)

    result = manifest.to_tool_result(summary=summary)
    assert not result.isError
    # Summary + resource link
    assert len(result.content) == 2
    assert result.content[0].type == "text"
    assert "Quarterly Report" in result.require_text()
    assert result.content[1].type == "resource_link"
    assert manifest.artifact_id in result.content[1].uri  # ty: ignore[unresolved-attribute]


@pytest.mark.integration
async def test_builder_document_through_mcp(tmp_path) -> None:
    """Prove the DocumentBuilder → store → MCP pipeline works."""
    runtime = _make_runtime(tmp_path)
    context = KaosContext.create(session_id="builder-test", runtime=runtime)

    # Build a document programmatically (as a PDF module would)
    doc = (
        DocumentBuilder(title="Extracted Contract")
        .set_metadata(authors=("PDF Extractor",), document_type="contract")
        .heading(1, "Article I — Definitions")
        .paragraph("The following terms shall have the meanings set forth below.")
        .heading(2, "Section 1.1 — Agreement")
        .paragraph("This Agreement means the entire document and all exhibits.")
        .heading(1, "Article II — Term")
        .paragraph("The term of this Agreement shall be three (3) years.")
        .build()
    )

    manifest = await store_document(
        doc,
        runtime,
        context,
        name="extracted-contract",
        description="Contract extracted from PDF",
    )

    app = create_app(runtime)

    async with create_connected_server_and_client_session(app) as session:
        # Read outline
        outline_result = await session.read_resource(
            AnyUrl(f"kaos://content/{manifest.artifact_id}/outline")
        )
        outline_content = outline_result.contents[0]
        assert isinstance(outline_content, types.TextResourceContents)
        outline = json.loads(outline_content.text)
        assert len(outline) >= 3
        depths = [h["depth"] for h in outline]
        assert 1 in depths
        assert 2 in depths

        # Read markdown
        md_result = await session.read_resource(
            AnyUrl(f"kaos://content/{manifest.artifact_id}/markdown")
        )
        md_content = md_result.contents[0]
        assert isinstance(md_content, types.TextResourceContents)
        assert "Article I" in md_content.text
        assert "Agreement" in md_content.text

        # Read sections tree
        sections_result = await session.read_resource(
            AnyUrl(f"kaos://content/{manifest.artifact_id}/sections")
        )
        sections_content = sections_result.contents[0]
        assert isinstance(sections_content, types.TextResourceContents)
        sections = json.loads(sections_content.text)
        assert len(sections) >= 2  # Article I, Article II
        assert any(s["heading_text"] == "Article I \u2014 Definitions" for s in sections)

        # Read single section markdown
        # Find Article I ref
        article_ref = next(s["heading_ref"] for s in sections if "Article I" in s["heading_text"])
        encoded_ref = article_ref.lstrip("#/").replace("/", "%2F")
        section_result = await session.read_resource(
            AnyUrl(f"kaos://content/{manifest.artifact_id}/sections/{encoded_ref}")
        )
        section_content = section_result.contents[0]
        assert isinstance(section_content, types.TextResourceContents)
        assert "Definitions" in section_content.text
        assert "Agreement" in section_content.text  # Subsection content included
