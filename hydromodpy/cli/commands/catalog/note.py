"""``hmp catalog note`` - append a timestamped note to a run, in its ``annotations.json``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli._conventions import add_sim_ref, verbosity_parser, workspace_parser
from hydromodpy.cli.helpers import apply_verbosity, exit_code_for
from hydromodpy.core.state.paths import catalog_path_for, resolve_project_root

NAME: str = "note"
HELP: str = "Append a timestamped note to a run"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), verbosity_parser()],
        epilog='Example:\n  hmp catalog note calibration "best fit after widening Sy bounds"',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_sim_ref(parser)
    parser.add_argument(
        "--site",
        default=None,
        help="Narrow an @-selector (@last, @best:nse) to the runs of one site",
    )
    parser.add_argument("text", help="Note text")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    apply_verbosity(args, {})
    from hydromodpy.core.auth import get_auth_backend
    from hydromodpy.results.annotations import add_note
    from hydromodpy.results.catalog.discovery import resolve_rel_dir

    root = resolve_project_root(
        Path(getattr(args, "workspace", None) or Path.cwd()).expanduser().resolve()
    )
    try:
        rel_dir = resolve_rel_dir(root, args.sim_ref, site=args.site)
        add_note(root / rel_dir, str(args.text), author=get_auth_backend().current_user())
    except Exception as exc:  # noqa: BLE001 - map resolver and IO errors to exit codes
        print(str(exc), file=sys.stderr)
        sys.exit(exit_code_for(exc))
    if catalog_path_for(root).is_file():
        from hydromodpy.results.catalog.indexer import index_new_runs

        index_new_runs(root)
    print(f"noted [{rel_dir}]")
