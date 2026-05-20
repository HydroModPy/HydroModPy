"""HTTP server bits for ``hmp dev manage``: handler and asset loader."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler
from importlib import resources
from typing import Any
from urllib.parse import parse_qs, urlparse

from hydromodpy.cli.commands.dev.manage.backend import _WorkspaceManagerBackend


def load_index_html() -> str:
    """Return the static dashboard HTML bundled as a package resource."""
    return (
        resources.files("hydromodpy.cli.commands.dev.manage.static")
        .joinpath("index.html")
        .read_text(encoding="utf-8")
    )


class _WorkspaceManagerHandler(BaseHTTPRequestHandler):
    """Serve one small HTML app and a handful of JSON endpoints."""

    server_version = "HydroModPyManage/1.0"

    @property
    def backend(self) -> _WorkspaceManagerBackend:
        return self.server.backend  # type: ignore[attr-defined]

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._write_html(load_index_html())
            return
        if parsed.path == "/api/workspaces":
            self._write_json(200, self.backend.list_workspaces())
            return
        query = parse_qs(parsed.query)
        workspace_ref = query.get("workspace", [None])[0]
        if parsed.path == "/api/summary":
            self._write_json(200, self.backend.summary(workspace_ref))
            return
        if parsed.path == "/api/simulations":
            self._write_json(200, self.backend.list_simulations(workspace_ref))
            return
        if parsed.path == "/api/orphans":
            self._write_json(200, self.backend.list_orphans(workspace_ref))
            return
        if parsed.path == "/api/diagnostics":
            self._write_json(200, self.backend.result_diagnostics(workspace_ref))
            return
        if parsed.path == "/api/tables":
            database = query.get("database", ["catalog"])[0]
            self._write_json(200, self.backend.list_tables(workspace_ref, database))
            return
        if parsed.path == "/api/preview":
            database = query.get("database", ["catalog"])[0]
            table = query.get("table", [""])[0]
            limit = int(query.get("limit", ["100"])[0])
            try:
                payload = self.backend.preview_table(workspace_ref, database, table, limit)
            except Exception as exc:
                self._write_json(400, {"error": str(exc)})
                return
            self._write_json(200, payload)
            return
        self._write_json(404, {"error": f"Unknown route: {parsed.path}"})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            payload = self._read_json()
        except Exception as exc:
            self._write_json(400, {"error": f"Invalid JSON body: {exc}"})
            return

        try:
            if parsed.path == "/api/delete-simulations":
                sim_ids = [str(item) for item in payload.get("sim_ids", []) if str(item).strip()]
                workspace_ref = payload.get("workspace")
                self._write_json(
                    200,
                    self.backend.delete_simulations(
                        str(workspace_ref) if workspace_ref is not None else None,
                        sim_ids,
                    ),
                )
                return
            if parsed.path == "/api/delete-orphans":
                paths = [str(item) for item in payload.get("paths", []) if str(item).strip()]
                workspace_ref = payload.get("workspace")
                self._write_json(
                    200,
                    self.backend.delete_orphans(
                        str(workspace_ref) if workspace_ref is not None else None,
                        paths,
                    ),
                )
                return
        except Exception as exc:
            self._write_json(400, {"error": str(exc)})
            return

        self._write_json(404, {"error": f"Unknown route: {parsed.path}"})

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length > 0 else b"{}"
        data = json.loads(raw.decode("utf-8"))
        return data if isinstance(data, dict) else {}

    def _write_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _write_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
