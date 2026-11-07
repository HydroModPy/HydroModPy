"""``hmp campaign promote`` - turn one trial of a calibration session into a run.

Thin wrapper over
:func:`hydromodpy.calibration.runners.promotion.promote_trial_from_session`:
a trial kept under ``sessions/<case>/trials/<n>/`` is moved, any other trial
is replayed from the frozen session configuration after its fingerprint is
checked. The run lands in ``runs/<case>`` paired with the session when that
name is free, else in the next version, or under ``--name``. Without
``--trial``, the five completed trials of lowest cost of each phase are listed to choose from.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli.conventions import format_parser, verbosity_parser, workspace_parser
from hydromodpy.cli.helpers import resolve_project
from hydromodpy.cli.output import emit

NAME: str = "promote"
HELP: str = "Promote one trial of a calibration session to a run under runs/"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), format_parser(), verbosity_parser()],
        epilog=(
            "The case names the session: sessions/<case>[.vN].\n"
            "\n"
            "Examples:\n"
            "  hmp campaign promote calibration\n"
            "  hmp campaign promote calibration --trial 12\n"
            "  hmp campaign promote J0014010-calage --trial 4 --name k_high -w projects/bretagne"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("case", help="Case of the session, <case> or <case>.vN")
    parser.add_argument(
        "--trial",
        type=int,
        default=None,
        metavar="N",
        help="Trial number, as trials.jsonl of the session lists it (default: list the best)",
    )
    parser.add_argument(
        "--name",
        default=None,
        metavar="NAME",
        help="Run name to take (default: the case, paired with the session when free)",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.calibration.runners.promotion import promote_trial_from_session
    from hydromodpy.core.state.result_dirs import run_dir_rel

    project_root = resolve_project(args.workspace)
    if args.trial is None:
        _list_best_trials(args, project_root)
        return
    run_dir = promote_trial_from_session(project_root, args.case, args.trial, as_name=args.name)
    from hydromodpy.results.catalog.indexer import reindex_if_indexed

    reindex_if_indexed(project_root)
    rel_dir = run_dir_rel(run_dir.name)

    def table() -> None:
        print(f"promoted trial {args.trial} of {args.case} to {rel_dir}")
        print(f"next: hmp catalog show {run_dir.name} -w {project_root}")

    emit(
        args,
        "campaign promote",
        {"case": args.case, "trial": args.trial, "rel_dir": rel_dir},
        table=table,
    )


def _list_best_trials(args: argparse.Namespace, project_root: Path) -> None:
    """List the five completed trials of lowest cost of each phase, with the values each tried."""
    from hydromodpy.calibration.runners.promotion import best_trials
    from hydromodpy.results.session.journal import physical_parameters

    best = best_trials(project_root, args.case)
    rows = [
        {
            "trial": t.trial,
            "phase": t.phase,
            "cost": t.cost,
            "values": physical_parameters(t),
        }
        for t in best
    ]

    def table() -> None:
        for row in rows:
            values = ", ".join(f"{name} = {value:.4g}" for name, value in row["values"].items())
            print(f"trial {row['trial']} ({row['phase']}): cost {row['cost']:.4g}, {values}")
        print(f"next: hmp campaign promote {args.case} --trial N", file=sys.stderr)

    emit(args, "campaign promote", rows, table=table)
