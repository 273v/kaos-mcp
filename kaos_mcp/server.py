from __future__ import annotations

from kaos_core import KaosRuntime
from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette

from kaos_mcp.app import create_app
from kaos_mcp.config import KaosMCPSettings


class KaosMCPServer:
    def __init__(
        self,
        runtime: KaosRuntime | None = None,
        settings: KaosMCPSettings | None = None,
    ) -> None:
        self.runtime = runtime or KaosRuntime.default()
        self.settings = settings or KaosMCPSettings()
        self._app: FastMCP | None = None

    def build_app(self) -> FastMCP:
        if self._app is None:
            self._app = create_app(self.runtime, self.settings)
        return self._app

    def run_stdio(self) -> None:
        self.build_app().run(transport="stdio", mount_path=self.settings.mount_path)

    def run_streamable_http(self) -> None:
        self.build_app().run(transport="streamable-http", mount_path=self.settings.mount_path)

    def streamable_http_app(self) -> Starlette:
        return self.build_app().streamable_http_app()
