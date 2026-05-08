"""Tests for the kaos-mcp CLI (kaos_mcp.cli)."""

from __future__ import annotations

import json
from io import StringIO
from unittest.mock import patch

import pytest

from kaos_mcp.cli import main


class TestListTools:
    def test_list_tools_human(self):
        stdout = StringIO()
        with patch("sys.stdout", stdout):
            main(["list-tools"])
        # May be empty or have tools — just verify it runs
        output = stdout.getvalue()
        assert isinstance(output, str)

    def test_list_tools_json(self):
        stdout = StringIO()
        with patch("sys.stdout", stdout):
            main(["list-tools", "--json"])
        data = json.loads(stdout.getvalue())
        assert data["command"] == "list-tools"
        assert "total" in data
        assert "tools" in data
        assert isinstance(data["tools"], list)


class TestListResources:
    def test_list_resources_human(self):
        stdout = StringIO()
        with patch("sys.stdout", stdout):
            main(["list-resources"])
        output = stdout.getvalue()
        assert isinstance(output, str)

    def test_list_resources_json(self):
        stdout = StringIO()
        with patch("sys.stdout", stdout):
            main(["list-resources", "--json"])
        data = json.loads(stdout.getvalue())
        assert data["command"] == "list-resources"
        assert "total" in data
        assert "resources" in data
        assert isinstance(data["resources"], list)


class TestJsonEnvelope:
    def test_list_tools_envelope(self):
        stdout = StringIO()
        with patch("sys.stdout", stdout):
            main(["list-tools", "--json"])
        data = json.loads(stdout.getvalue())
        assert "command" in data
        assert "total" in data

    def test_list_resources_envelope(self):
        stdout = StringIO()
        with patch("sys.stdout", stdout):
            main(["list-resources", "--json"])
        data = json.loads(stdout.getvalue())
        assert "command" in data
        assert "total" in data


class TestErrorHandling:
    def test_no_command(self):
        with pytest.raises(SystemExit):
            main([])

    def test_version(self):
        with pytest.raises(SystemExit) as exc_info:
            main(["--version"])
        assert exc_info.value.code == 0
