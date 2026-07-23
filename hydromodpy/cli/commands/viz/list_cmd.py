"""``hmp viz list`` - print the registered figure names and their requirements."""

from __future__ import annotations

import argparse

NAME: str = "list"
HELP: str = "List the figure names accepted by [display].figures"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument(
        "--kind",
        default=None,
        metavar="KIND",
        help="Only list figures of this kind (spatial, section, timeseries, ...)",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
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
