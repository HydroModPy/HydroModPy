"""``hmp dev manage`` - browser UI for workspace inspection and cleanup."""

from __future__ import annotations

import argparse
import sys
import webbrowser
from http.server import ThreadingHTTPServer
from pathlib import Path

from hydromodpy.cli.commands.dev.manage.backend import _WorkspaceManagerBackend
from hydromodpy.cli.commands.dev.manage.server import _WorkspaceManagerHandler, load_index_html
from hydromodpy.cli.helpers import EXIT_CONFIG, resolve_workspace

NAME = "manage"
HELP = "Open a local browser UI to inspect DuckDB tables and manage simulations"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument(
        "--workspace",
        default=None,
        help="Single workspace root to manage directly",
    )
    parser.add_argument(
        "--scan-root",
        default=None,
        help="Recursively discover every HydroModPy workspace under this root "
        "(default: current directory when --workspace is omitted)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="Bind port (default: 0 for auto-assigned local port)",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Start the server without opening a browser tab",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    try:
        import duckdb  # noqa: F401
    except ImportError:
        print(
            "DuckDB is required for 'hmp manage'. Reinstall the project dependencies first: "
            "pip install -e .",
            file=sys.stderr,
        )
        sys.exit(EXIT_CONFIG)

    workspace_arg = getattr(args, "workspace", None)
    scan_root_arg = getattr(args, "scan_root", None)
    if workspace_arg:
        workspace_root = resolve_workspace(workspace_arg)
        backend = _WorkspaceManagerBackend(workspace_root=workspace_root)
    else:
        scan_root = (
            Path(scan_root_arg).expanduser().resolve() if scan_root_arg else Path.cwd().resolve()
        )
        backend = _WorkspaceManagerBackend(scan_root=scan_root)
    server = ThreadingHTTPServer((args.host, args.port), _WorkspaceManagerHandler)
    server.backend = backend  # type: ignore[attr-defined]

    host, port = server.server_address[:2]
    url = f"http://{host}:{port}/"
    print(f"Workspace manager running at {url}")
    print(f"Discovered {len(backend.workspace_roots)} workspace(s).")
    print("Press Ctrl+C to stop.")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


__all__ = (
    "NAME",
    "HELP",
    "register",
    "run",
    "load_index_html",
    "_WorkspaceManagerBackend",
    "_WorkspaceManagerHandler",
)
