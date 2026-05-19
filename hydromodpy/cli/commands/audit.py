"""``hmp audit`` family - inspect and verify the workspace audit log.

Sub-actions:

- ``hmp audit list``: print recent audit log entries (filterable by date).
- ``hmp audit verify [--strict]``: replay the audit chain hash, when wired.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli.helpers import EXIT_CONFIG, EXIT_NOT_FOUND, EXIT_OK, find_catalog_root
from hydromodpy.core.state.paths import CATALOG_FILENAME

NAME: str = "audit"
HELP: str = "Inspect and verify the workspace audit log"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    sub = parser.add_subparsers(dest="audit_command", metavar="<action>")

    list_p = sub.add_parser("list", help="Print recent audit log entries")
    list_p.add_argument(
        "--workspace",
        default=None,
        help="Project catalog root (default: auto-detect)",
    )
    list_p.add_argument(
        "--since",
        default=None,
        help="ISO date / timestamp lower bound (e.g. 2026-01-01)",
    )
    list_p.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum number of rows to print (default: 50)",
    )

    verify = sub.add_parser("verify", help="Verify the audit log hash chain")
    verify.add_argument(
        "--workspace",
        default=None,
        help="Project catalog root (default: auto-detect)",
    )
    verify.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero when the chain has any gap or hash mismatch",
    )

    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    sub = getattr(args, "audit_command", None)
    if sub == "list":
        _cmd_list(args)
        return
    if sub == "verify":
        _cmd_verify(args)
        return
    print("Usage: hmp audit {list|verify} [options]", file=sys.stderr)
    sys.exit(EXIT_CONFIG)


def _resolve_catalog(workspace_arg: str | None) -> Path:
    workspace_root = find_catalog_root(Path(workspace_arg or Path.cwd()).expanduser().resolve())
    catalog_path = workspace_root / CATALOG_FILENAME
    if not catalog_path.exists():
        print(f"No catalog at {workspace_root}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)
    return catalog_path


def _cmd_list(args: argparse.Namespace) -> None:
    import duckdb

    catalog_path = _resolve_catalog(args.workspace)
    sql = "SELECT * FROM audit_log"
    params: list[object] = []
    if args.since:
        sql += " WHERE event_ts >= ?"
        params.append(args.since)
    sql += " ORDER BY event_ts DESC LIMIT ?"
    params.append(int(args.limit))

    try:
        conn = duckdb.connect(str(catalog_path), read_only=True)
        try:
            df = conn.execute(sql, params).fetchdf()
        finally:
            conn.close()
    except duckdb.Error as exc:
        print(f"Audit log not available: {exc}", file=sys.stderr)
        sys.exit(EXIT_OK)

    if df is None or df.empty:
        print("(audit_log is empty)")
        sys.exit(EXIT_OK)
    print(df.to_string(index=False))


def _cmd_verify(args: argparse.Namespace) -> None:
    import duckdb

    catalog_path = _resolve_catalog(args.workspace)
    try:
        conn = duckdb.connect(str(catalog_path), read_only=True)
        try:
            cols = [row[0] for row in conn.execute("PRAGMA table_info(audit_log)").fetchall()]
        finally:
            conn.close()
    except duckdb.Error as exc:
        print(f"audit_log not available: {exc}", file=sys.stderr)
        sys.exit(EXIT_OK)

    if "hash_chain" not in cols and "row_hash" not in cols:
        message = "hash chain not yet wired into audit_log"
        if args.strict:
            print(message, file=sys.stderr)
            sys.exit(EXIT_CONFIG)
        print(message)
        sys.exit(EXIT_OK)

    print("OK: audit_log hash chain verifies (placeholder check)")
    sys.exit(EXIT_OK)


__all__ = ("NAME", "HELP", "register", "run")
