"""``hmp dev lock`` - thin wrapper around :func:`hydromodpy.lock_*` family.

``hydromodpy.lock`` belongs to a project root, while the data cache it pins
belongs to a workspace. ``update`` and ``verify`` therefore take both:
``--project`` names the lockfile, ``--workspace`` names the cache. Omitting
``--project`` resolves the project the current directory sits in, unless
``--output`` or ``--lockfile`` names the file outright: such a path is the
address already, and the directory it sits in is the project it describes.
Omitting ``--workspace`` resolves the workspace that holds that project.
"""

from __future__ import annotations

import argparse
import sys

from hydromodpy.cli.helpers import EXIT_CONFIG, EXIT_NOT_FOUND, EXIT_VALIDATION

NAME: str = "lock"
HELP: str = "Manage the reproducible data lockfile (hydromodpy.lock)"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    sub = parser.add_subparsers(dest="lock_command")

    update = sub.add_parser("update", help="Scan the cache and write/update hydromodpy.lock")
    update.add_argument("--project", default=None, help="Project root owning hydromodpy.lock")
    update.add_argument("--workspace", default=None, help="Workspace holding the data cache")
    update.add_argument("--output", default=None, help="Destination lockfile")

    archive = sub.add_parser("archive", help="Create a portable archive")
    archive.add_argument("output", help="Destination archive (.tar / .tar.gz / .tar.zst)")
    archive.add_argument("--workspace", default=None)

    restore = sub.add_parser("restore", help="Restore an archive and verify SHA-256")
    restore.add_argument("input", help="Archive to restore")
    restore.add_argument("--workspace", default=None)
    restore.add_argument("--output", default=None, help="Target directory")

    verify = sub.add_parser("verify", help="Verify the cache matches the lockfile")
    verify.add_argument("--project", default=None, help="Project root owning hydromodpy.lock")
    verify.add_argument("--workspace", default=None, help="Workspace holding the data cache")
    verify.add_argument("--lockfile", default=None, help="Explicit lockfile path")
    verify.add_argument("--strict", action="store_true", help="Strict input verification")

    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.dev import (
        lock_archive,
        lock_restore,
        lock_update,
        lock_verify,
    )

    sub = getattr(args, "lock_command", None)
    if sub == "update":
        try:
            written = lock_update(args.workspace, project=args.project, output=args.output)
        except FileNotFoundError as exc:
            print(f"  {exc}", file=sys.stderr)
            sys.exit(EXIT_NOT_FOUND)
        print(f"  Lockfile written: {written}")
        return
    if sub == "archive":
        dest = lock_archive(args.output, workspace=args.workspace)
        print(f"  Archive written: {dest}")
        return
    if sub == "restore":
        dest = lock_restore(args.input, workspace=args.workspace, output=args.output)
        print(f"  Restored {args.input} -> {dest}")
        return
    if sub == "verify":
        try:
            result = lock_verify(
                args.workspace,
                project=args.project,
                lockfile=args.lockfile,
                strict=args.strict,
            )
        except FileNotFoundError as exc:
            print(f"  {exc}", file=sys.stderr)
            sys.exit(EXIT_NOT_FOUND)
        if result["schema_diverged"]:
            label = "ERROR" if args.strict else "WARNING"
            print(
                f"  {label}: configuration schema has changed since freeze "
                f"(lockfile={result['locked_schema'][:12]}..., "
                f"current={result['current_schema'][:12]}...).",
                file=sys.stderr,
            )
            if args.strict:
                sys.exit(EXIT_VALIDATION)
        if result["ok"]:
            print("  OK: catalog matches lockfile")
            return
        label = "ERROR" if args.strict else "WARNING"
        mismatches = result["mismatches"]
        print(f"  {label}: {len(mismatches)} mismatch(es):")
        for m in mismatches:
            print(f"    [{m.kind}] {m.variable}/{m.source}/{m.station_id} -> {m.path}")
        sys.exit(EXIT_VALIDATION)
    print("Usage: hmp dev lock {update|archive|restore|verify} [options]", file=sys.stderr)
    sys.exit(EXIT_CONFIG)
