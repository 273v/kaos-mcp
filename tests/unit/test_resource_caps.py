"""Regression tests for audit-02 F4: resource read DoS caps.

Settings on ``KaosMCPSettings``:
- ``max_resource_bytes`` (default 10 MiB) — bounds artifact body reads.
- ``max_range_length`` (default 10 MiB) — bounds caller-supplied range
  length on ``kaos://artifacts/{id}/range/{start}/{length}``.
- ``max_table_rows`` (default 100,000) — bounds caller-supplied row
  count on ``kaos://tabular/{id}/table/{name}/rows/{start}/{count}``.
"""

from __future__ import annotations

import pytest
from kaos_core import KaosContext, KaosRuntime

from kaos_mcp import create_app
from kaos_mcp.config import KaosMCPSettings


class TestRangeLengthCap:
    @pytest.mark.unit
    async def test_range_length_over_cap_rejected(self, runtime: KaosRuntime) -> None:
        ctx = KaosContext.create(session_id="cap-session", runtime=runtime)
        await ctx.get_vfs_path("artifacts/range.txt").write_text("hello world")
        manifest = await runtime.artifacts.create_from_path(
            "artifacts/range.txt",
            context_id="cap-session",
            session_id="cap-session",
            name="range",
            mime_type="text/plain",
        )

        # Cap range length to 4 bytes; request 5000.
        settings = KaosMCPSettings(name="range-cap", max_range_length=4)
        app = create_app(runtime, settings)

        with pytest.raises(ValueError, match="exceeds max_range_length"):
            await app.read_resource(f"kaos://artifacts/{manifest.artifact_id}/range/0/5000")

    @pytest.mark.unit
    async def test_range_length_at_cap_allowed(self, runtime: KaosRuntime) -> None:
        ctx = KaosContext.create(session_id="cap-session-2", runtime=runtime)
        await ctx.get_vfs_path("artifacts/range2.txt").write_text("hello world")
        manifest = await runtime.artifacts.create_from_path(
            "artifacts/range2.txt",
            context_id="cap-session-2",
            session_id="cap-session-2",
            name="range2",
            mime_type="text/plain",
        )

        # Cap exactly at request length.
        settings = KaosMCPSettings(name="range-at-cap", max_range_length=4)
        app = create_app(runtime, settings)

        contents = list(
            await app.read_resource(f"kaos://artifacts/{manifest.artifact_id}/range/0/4")
        )
        assert contents[0].content == b"hell"


class TestTabularRowCountCap:
    @pytest.mark.unit
    async def test_row_count_over_cap_rejected(self, runtime: KaosRuntime) -> None:
        # Build a minimal tabular artifact (TabularDocument JSON envelope).
        # We don't need real content because the cap fires before load_tabular.
        ctx = KaosContext.create(session_id="rows-session", runtime=runtime)
        await ctx.get_vfs_path("artifacts/table.json").write_text("{}")
        manifest = await runtime.artifacts.create_from_path(
            "artifacts/table.json",
            context_id="rows-session",
            session_id="rows-session",
            name="table",
            mime_type="application/json",
        )

        settings = KaosMCPSettings(name="rows-cap", max_table_rows=10)
        app = create_app(runtime, settings)

        # 1_000_000 rows is far over the 10-row cap — must fail with the
        # cap message, not a tabular-parse error.
        with pytest.raises(ValueError, match="max_table_rows"):
            await app.read_resource(f"kaos://tabular/{manifest.artifact_id}/table/x/rows/0/1000000")


class TestResourceBytesCap:
    @pytest.mark.unit
    async def test_oversize_content_document_rejected(self, runtime: KaosRuntime) -> None:
        ctx = KaosContext.create(session_id="bytes-session", runtime=runtime)
        # 200 bytes payload, cap at 32 bytes.
        big_payload = "x" * 200
        await ctx.get_vfs_path("artifacts/big.json").write_text(big_payload)
        manifest = await runtime.artifacts.create_from_path(
            "artifacts/big.json",
            context_id="bytes-session",
            session_id="bytes-session",
            name="big",
            mime_type="application/json",
        )

        settings = KaosMCPSettings(name="bytes-cap", max_resource_bytes=32)
        app = create_app(runtime, settings)

        with pytest.raises(ValueError, match="inline read limit"):
            await app.read_resource(f"kaos://content/{manifest.artifact_id}")

    @pytest.mark.unit
    async def test_oversize_tabular_json_rejected(self, runtime: KaosRuntime) -> None:
        ctx = KaosContext.create(session_id="bytes-session-2", runtime=runtime)
        big_payload = "y" * 200
        await ctx.get_vfs_path("artifacts/big_tab.json").write_text(big_payload)
        manifest = await runtime.artifacts.create_from_path(
            "artifacts/big_tab.json",
            context_id="bytes-session-2",
            session_id="bytes-session-2",
            name="big-tab",
            mime_type="application/json",
        )

        settings = KaosMCPSettings(name="tabular-bytes-cap", max_resource_bytes=32)
        app = create_app(runtime, settings)

        with pytest.raises(ValueError, match="inline read limit"):
            await app.read_resource(f"kaos://tabular/{manifest.artifact_id}")
