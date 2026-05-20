"""``hmp audit`` - thin wrapper around :func:`hydromodpy.audit_list` and ``audit_verify``."""

from __future__ import annotations

import argparse
import sys

from hydromodpy.cli.helpers import EXIT_CONFIG, EXIT_NOT_FOUND, EXIT_OK

NAME: str = "audit"
HELP: str = "Inspect and verify the workspace audit log"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    sub = parser.add_subparsers(dest="audit_command", metavar="<action>")

    list_p = sub.add_parser("list", help="Print recent audit log entries")
    list_p.add_argument("--workspace", default=None)
    list_p.add_argument("--since", default=None, help="ISO date / timestamp lower bound")
    list_p.add_argument("--limit", type=int, default=50)

    verify = sub.add_parser("verify", help="Verify the audit log hash chain")
    verify.add_argument("--workspace", default=None)
    verify.add_argument("--strict", action="store_true")

    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.audit import audit_list, audit_verify

    sub = getattr(args, "audit_command", None)
    if sub == "list":
        try:
            df = audit_list(args.workspace, since=args.since, limit=args.limit)
        except FileNotFoundError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(EXIT_NOT_FOUND)
        if df is None or df.empty:
            print("(audit_log is empty)")
        else:
            print(df.to_string(index=False))
        sys.exit(EXIT_OK)
    if sub == "verify":
        try:
            result = audit_verify(args.workspace, strict=args.strict)
        except FileNotFoundError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(EXIT_NOT_FOUND)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(EXIT_CONFIG)
        print(result["message"])
        sys.exit(EXIT_OK)
    print("Usage: hmp audit {list|verify} [options]", file=sys.stderr)
    sys.exit(EXIT_CONFIG)


__all__ = ("NAME", "HELP", "register", "run")
