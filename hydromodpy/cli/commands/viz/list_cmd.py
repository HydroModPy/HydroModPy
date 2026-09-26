"""``hmp viz list`` - print the registered figure names and their requirements.

With ``--run``, print for each figure whether that run supports it, or the
reason it does not.
"""

from __future__ import annotations

import argparse
import sys

from hydromodpy.cli._conventions import verbosity_parser
from hydromodpy.cli.helpers import EXIT_NOT_FOUND, apply_verbosity

NAME: str = "list"
HELP: str = "List the figure names accepted by [display].figures"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP, parents=[verbosity_parser()])
    parser.add_argument(
        "--kind",
        default=None,
        metavar="KIND",
        help="Only list figures of this kind (spatial, section, timeseries, ...)",
    )
    parser.add_argument(
        "--run",
        dest="sim_ref",
        default=None,
        metavar="SIM_REF",
        help=(
            "Say for each figure whether this run supports it, or why not "
            "(sim_id, unique prefix, name or @-selector)"
        ),
    )
    parser.add_argument("--workspace", default=None, help="Project catalog root (with --run)")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    apply_verbosity(args, {})
    if args.sim_ref is not None:
        _list_for_run(args)
        return
    from hydromodpy.display import list_figures

    specs = [spec for spec in list_figures() if args.kind in (None, spec.kind)]
    for spec in specs:
        requirements = []
        if spec.required_fields:
            requirements.append("fields " + ", ".join(spec.required_fields))
        if spec.required_tables:
            requirements.append("tables " + ", ".join(spec.required_tables))
        if spec.required_solvers:
            requirements.append("solvers " + ", ".join(spec.required_solvers))
        needs = "; ".join(requirements) or "no declared requirement"
        print(f"{spec.name:44s} {spec.kind:11s} {needs}")
    print(f"\n{len(specs)} figure(s)")


def _list_for_run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.viz import figure_availability
    from hydromodpy.results.catalog import (
        AmbiguousReferenceError,
        SimulationNotFoundError,
    )

    try:
        rows = figure_availability(args.sim_ref, workspace=args.workspace)
    except (AmbiguousReferenceError, SimulationNotFoundError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)
    rows = [(spec, reason) for spec, reason in rows if args.kind in (None, spec.kind)]
    for spec, reason in rows:
        print(f"{spec.name:44s} {spec.kind:11s} {'available' if reason is None else reason}")
    supported = sum(reason is None for _, reason in rows)
    print(f"\n{len(rows)} figure(s), {supported} available for {args.sim_ref}")
