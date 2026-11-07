"""``hmp viz list`` - print the registered figure names and their requirements.

With ``--run``, print for each figure whether that run supports it, or the
reason it does not.
"""

from __future__ import annotations

import argparse

from hydromodpy.cli.conventions import format_parser, verbosity_parser, workspace_parser
from hydromodpy.cli.output import emit

NAME: str = "list"
HELP: str = "List the figure names accepted by [display].figures"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), format_parser(), verbosity_parser()],
        epilog="Examples:\n  hmp viz list\n  hmp viz list --kind balance",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
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
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    if args.sim_ref is not None:
        _list_for_run(args)
        return
    from hydromodpy.display import list_figures

    specs = [spec for spec in list_figures() if args.kind in (None, spec.kind)]

    def table() -> None:
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

    emit(
        args,
        "viz list",
        [
            {
                "name": spec.name,
                "kind": spec.kind,
                "required_fields": list(spec.required_fields),
                "required_tables": list(spec.required_tables),
                "required_solvers": list(spec.required_solvers),
            }
            for spec in specs
        ],
        table=table,
    )


def _list_for_run(args: argparse.Namespace) -> None:
    from hydromodpy.display.catalog_figures import figure_availability

    rows = figure_availability(args.sim_ref, workspace=args.workspace)
    rows = [(spec, reason) for spec, reason in rows if args.kind in (None, spec.kind)]

    def table() -> None:
        for spec, reason in rows:
            print(f"{spec.name:44s} {spec.kind:11s} {'available' if reason is None else reason}")
        supported = sum(reason is None for _, reason in rows)
        print(f"\n{len(rows)} figure(s), {supported} available for {args.sim_ref}")

    emit(
        args,
        "viz list run",
        [
            {"name": spec.name, "kind": spec.kind, "available": reason is None, "reason": reason}
            for spec, reason in rows
        ],
        table=table,
    )
