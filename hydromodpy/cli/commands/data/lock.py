"""``hmp data lock`` - write ``hydromodpy.lock``, or check the files against it.

``hydromodpy.lock`` belongs to a project root, while the data cache it pins
belongs to a workspace. So the verb takes both: ``--project`` names the
lockfile, ``-w`` names the cache. Omitting ``--project`` resolves the project
the current directory sits in, unless ``--to`` or ``--lockfile`` names the file
outright: such a path is the address already, and the directory it sits in is
the project it describes. Omitting ``-w`` resolves the workspace that holds that
project.

``hmp data lock`` writes the digest, the source and the licence of each row of
the cache, and of each user file the configurations of the project declare.
``hmp data lock --check`` compares the files on disk with the lockfile, and
``--strict`` also refuses when the configuration schema changed since it was written.
"""

from __future__ import annotations

import argparse
import sys

from hydromodpy.cli.conventions import (
    add_destination,
    format_parser,
    verbosity_parser,
    workspace_parser,
)
from hydromodpy.cli.helpers import EXIT_USAGE, EXIT_VALIDATION, refuse
from hydromodpy.cli.output import emit

NAME: str = "lock"
HELP: str = "Write the lockfile that pins the data of a project, or check the files against it"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), format_parser(), verbosity_parser()],
        epilog=(
            "Examples:\n  hmp data lock --project path/to/project\n"
            "  hmp data lock --check --project path/to/project --strict"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--project", default=None, help="Project root owning hydromodpy.lock")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Compare the files on disk with the lockfile instead of writing it",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="With --check: check the files the lockfile names, and refuse a changed schema",
    )
    add_destination(parser, help="Destination lockfile (when writing)", metavar="FILE")
    parser.add_argument("--lockfile", default=None, help="Lockfile to check (with --check)")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    if args.check:
        if args.to:
            refuse(
                "--to names where a lockfile is written. With --check, use --lockfile.", EXIT_USAGE
            )
        _check(args)
        return
    for flag, value in (("--strict", args.strict), ("--lockfile", args.lockfile)):
        if value:
            refuse(f"{flag} goes with --check.", EXIT_USAGE)
    _write(args)


def _write(args: argparse.Namespace) -> None:
    from hydromodpy.project.data_cache import lock_data

    written = lock_data(args.workspace, project=args.project, output=args.to)
    for path, reason in written.refused_configs:
        print(f"  WARNING: {path} is not locked, it does not load: {reason}", file=sys.stderr)

    def table() -> None:
        print(
            f"  Lockfile written: {written.path} "
            f"({written.inputs} input(s), {written.user_files} of them user files)"
        )

    emit(
        args,
        "data lock",
        {
            "path": written.path,
            "inputs": written.inputs,
            "user_files": written.user_files,
            "refused_configs": [
                {"path": path, "reason": reason} for path, reason in written.refused_configs
            ],
        },
        table=table,
    )


def _check(args: argparse.Namespace) -> None:
    from hydromodpy.project.data_cache import verify_data_lock

    result = verify_data_lock(
        args.workspace, project=args.project, lockfile=args.lockfile, strict=args.strict
    )
    label = "ERROR" if args.strict else "WARNING"
    mismatches = result["mismatches"]
    if result["schema_diverged"]:
        print(
            f"  {label}: configuration schema has changed since the lockfile was written "
            f"(lockfile={result['locked_schema'][:12]}..., "
            f"current={result['current_schema'][:12]}...).",
            file=sys.stderr,
        )

    def table() -> None:
        if result["ok"]:
            print("  OK: the data cache matches the lockfile")
            return
        print(f"  {label}: {len(mismatches)} mismatch(es):")
        for mismatch in mismatches:
            print(
                f"    [{mismatch.kind}] {mismatch.variable}/{mismatch.source}/"
                f"{mismatch.station_id} -> {mismatch.path}"
            )

    emit(args, "data lock check", result, table=table)
    if not result["ok"] or (args.strict and result["schema_diverged"]):
        sys.exit(EXIT_VALIDATION)
