"""Guard the installed-dependency contract for the ``mcp`` SDK.

``mcp`` 2.0 removed ``mcp.server.fastmcp``; an unbounded requirement let a
fresh ``pip install kaos-mcp`` resolve 2.x and fail at import time.
The floor tracks the oldest mcp release without known advisories.
"""

from importlib.metadata import requires, version

from packaging.requirements import Requirement
from packaging.version import Version


def _mcp_requirement() -> Requirement:
    for raw in requires("kaos-mcp") or []:
        req = Requirement(raw)
        if req.name == "mcp" and req.marker is None:
            return req
    raise AssertionError("kaos-mcp does not declare an unconditional mcp requirement")


def test_mcp_requirement_excludes_v2() -> None:
    spec = _mcp_requirement().specifier
    assert not spec.contains(Version("2.0.0"))
    assert spec.contains(Version("1.28.1"))


def test_mcp_requirement_excludes_vulnerable_v1() -> None:
    # PYSEC-2026-3481/3482/3483 are fixed in mcp 1.28.1.
    assert not _mcp_requirement().specifier.contains(Version("1.28.0"))


def test_installed_mcp_exposes_fastmcp() -> None:
    assert Version(version("mcp")) < Version("2")
    from mcp.server.fastmcp import FastMCP

    assert FastMCP is not None
