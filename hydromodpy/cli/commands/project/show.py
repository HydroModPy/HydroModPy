"""``hmp project show`` - thin wrapper around :func:`hydromodpy.show_project`."""

from __future__ import annotations

import argparse
import sys

from hydromodpy.cli.helpers import EXIT_NOT_FOUND
from hydromodpy.core.state.paths import (
    CATALOG_FILENAME,
    INTERNAL_DIRNAME,
    PROJECT_TOML_FILENAME,
)

NAME: str = "show"
HELP: str = "Show a project summary (TOMLs, catalog stats)"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument("project", help="Project name (directory under projects/)")
    parser.add_argument("--workspace", default=None, help="Workspace root")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.project import show_project

    try:
        payload = show_project(args.project, workspace=args.workspace)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    print(f"# project: {payload['name']}")
    print(f"# path   : {payload['path']}")
    state = "present" if payload["has_project_toml"] else "missing"
    print(f"  {PROJECT_TOML_FILENAME:<24} {state}")
    runs = payload["run_tomls"]
    if runs:
        print(f"  run TOMLs ({len(runs)}):")
        for name in runs:
            print(f"    - {name}")
    sims = payload.get("simulations") or []
    if sims:
        print(f"  simulations: {len(sims)}")
        for sim in sims[:10]:
            print(
                f"    - {sim['name']}  [{sim['short_id']}]  "
                f"solver={sim['solver']}  status={sim['status']}"
            )
        if len(sims) > 10:
            print(f"    ... {len(sims) - 10} more (use 'hmp catalog ls')")
    elif "catalog_error" in payload:
        print(f"  Error reading project catalog: {payload['catalog_error']}", file=sys.stderr)
    else:
        index_label = f"{INTERNAL_DIRNAME}/{CATALOG_FILENAME}"
        print(f"  {index_label:<24} missing")
