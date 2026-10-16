"""``hmp catalog import`` - bring a run published by ``hmp publish`` into the project."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli._conventions import verbosity_parser, workspace_parser
from hydromodpy.cli.helpers import apply_verbosity, exit_code_for
from hydromodpy.core.state.paths import catalog_path_for, resolve_project_root

NAME: str = "import"
HELP: str = "Import a run written by 'hmp publish' (directory or tar), digests checked first"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), verbosity_parser()],
        epilog=(
            "The run lands under runs/ with the next free version of its name,\n"
            "read without its .vN: a published x.v2 becomes x in a project that has\n"
            "no x. Pass --as to give it the name other documents cite.\n"
            "\n"
            "Examples:\n"
            "  hmp catalog import baseline.tar\n"
            "  hmp catalog import ../published/baseline --as lab_copy"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("source", help="Directory or tar written by 'hmp publish'")
    parser.add_argument(
        "--as",
        dest="as_name",
        default=None,
        help="Name of the imported run (default: the published name without its .vN)",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    apply_verbosity(args, {})
    from hydromodpy.results.catalog.registration import import_publication

    root = resolve_project_root(
        Path(getattr(args, "workspace", None) or Path.cwd()).expanduser().resolve()
    )
    try:
        rel_dir = import_publication(root, Path(args.source), name=args.as_name)
    except Exception as exc:  # noqa: BLE001 - map digest, conflict and IO errors
        print(str(exc), file=sys.stderr)
        sys.exit(exit_code_for(exc))
    if catalog_path_for(root).is_file():
        from hydromodpy.results.catalog.indexer import index_new_runs

        index_new_runs(root)
    print(f"imported {args.source} as {rel_dir}")
