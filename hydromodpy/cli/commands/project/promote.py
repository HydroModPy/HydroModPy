"""``hmp project promote`` - turn one trial of a calibration session into a run.

Thin wrapper over
:func:`hydromodpy.calibration.runners.promotion.promote_trial_from_session`:
a trial kept under ``sessions/<case>/trials/<n>/`` is moved, any other trial
is replayed from the frozen session configuration after its fingerprint is
checked. The run lands in ``runs/<case>`` paired with the session when that
name is free, else in the next version, or under ``--as``.
"""

from __future__ import annotations

import argparse

from hydromodpy.cli.conventions import verbosity_parser, workspace_parser
from hydromodpy.cli.helpers import apply_verbosity, resolve_project

NAME: str = "promote"
HELP: str = "Promote one trial of a calibration session to a run under runs/"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), verbosity_parser()],
        epilog=(
            "The case names the session: sessions/<case>[.vN].\n"
            "\n"
            "Examples:\n"
            "  hmp project promote calibration --trial 12\n"
            "  hmp project promote J0014010-calage --trial 4 --as k_high -w projects/bretagne"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("case", help="Case of the session, <case> or <case>.vN")
    parser.add_argument(
        "--trial",
        type=int,
        required=True,
        metavar="N",
        help="Trial number, as trials.jsonl of the session lists it",
    )
    parser.add_argument(
        "--as",
        dest="as_name",
        default=None,
        metavar="NAME",
        help="Run name to take (default: the case, paired with the session when free)",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    apply_verbosity(args, {})
    from hydromodpy.calibration.runners.promotion import promote_trial_from_session
    from hydromodpy.core.state.paths import catalog_path_for, run_dir_rel

    project_root = resolve_project(args.workspace)
    run_dir = promote_trial_from_session(project_root, args.case, args.trial, as_name=args.as_name)
    if catalog_path_for(project_root).is_file():
        from hydromodpy.results.catalog.indexer import index_new_runs

        index_new_runs(project_root)
    rel_dir = run_dir_rel(run_dir.name)
    print(f"promoted trial {args.trial} of {args.case} to {rel_dir}")
    print(f"next: hmp catalog show {run_dir.name} -w {project_root}")
