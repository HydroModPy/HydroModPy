"""``hmp catalog rename`` - move a run, and its session, to a new name."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli.conventions import add_sim_ref, verbosity_parser, workspace_parser
from hydromodpy.cli.helpers import apply_verbosity, exit_code_for
from hydromodpy.core.state.paths import catalog_path_for, resolve_project_root

NAME: str = "rename"
HELP: str = "Rename a run: runs/<old>/ and sessions/<old>/ move to the new name"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), verbosity_parser()],
        epilog=(
            "The directory is the name, so a rename moves runs/<old>/ and, for a\n"
            "calibration, sessions/<old>/ to the new name. Links between them are ids\n"
            "and stay valid. The new name must be free: a live directory, a trashed\n"
            "one or a tombstone holding it is refused.\n"
            "\n"
            "Example:\n"
            "  hmp catalog rename baseline.v2 baseline_k2e5"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_sim_ref(parser)
    parser.add_argument(
        "--site",
        default=None,
        help="Narrow an @-selector (@last, @best:nse) to the runs of one site",
    )
    parser.add_argument("new_name", help="New directory name")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    apply_verbosity(args, {})
    from hydromodpy.results.catalog.discovery import resolve_rel_dir
    from hydromodpy.results.catalog.registration import rename_case

    root = resolve_project_root(
        Path(getattr(args, "workspace", None) or Path.cwd()).expanduser().resolve()
    )
    try:
        rel_dir = resolve_rel_dir(root, args.sim_ref, site=args.site)
        renamed = rename_case(root, rel_dir, args.new_name)
    except Exception as exc:  # noqa: BLE001 - map resolver, collision and in-use errors
        print(str(exc), file=sys.stderr)
        sys.exit(exit_code_for(exc))
    if catalog_path_for(root).is_file():
        from hydromodpy.results.catalog.indexer import index_new_runs

        index_new_runs(root)
    print(f"renamed {rel_dir} -> {', '.join(renamed)}")
