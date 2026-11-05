"""``hmp workspace init`` - thin wrapper around :func:`hydromodpy.init_workspace`."""

from __future__ import annotations

import argparse

from hydromodpy.cli.conventions import format_parser, workspace_parser
from hydromodpy.cli.helpers import EXIT_CONFIG, refuse
from hydromodpy.cli.output import emit
from hydromodpy.core.state.layout import WORKSPACE_TOML_FILENAME

NAME: str = "init"
HELP: str = "Scaffold a HydroModPy workspace (data + projects). Default: ~/hydromodpy/"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), format_parser()],
        epilog="Examples:\n  hmp workspace init ~/hydromodpy\n  hmp workspace init ./ws --project-name my_project",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("path", nargs="?", default=None, help="Workspace path, or give it with -w")
    parser.add_argument(
        "--force", action="store_true", help="Go past the refusal: reuse a workspace that exists"
    )
    parser.add_argument(
        "--project-name",
        default=None,
        help="Project name written to workspace.toml (default: the workspace folder name)",
    )
    parser.add_argument(
        "--creator-name", default=None, help="Creator name written to workspace.toml"
    )
    parser.add_argument(
        "--creator-email", default=None, help="Creator e-mail written to workspace.toml"
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.workspace import init_workspace

    try:
        result = init_workspace(
            args.path or args.workspace,
            force=args.force,
            project_name=args.project_name,
            creator_name=args.creator_name,
            creator_email=args.creator_email,
        )
    except FileExistsError as exc:
        refuse(str(exc), EXIT_CONFIG, cause=exc)
    emit(args, "workspace init", result, table=lambda: _print_layout(result))


def _print_layout(result: dict[str, str]) -> None:
    """Print where the workspace is, what it holds and how to start."""
    from hydromodpy.data.workspace.scaffold import EXAMPLE_PROJECT_NAME, VARIABLES

    target = result["path"]
    print(f"Workspace: {target}")
    print(f"Scaffolded at {target}/. Add projects with 'hmp project new <name>'.")
    print()
    print("Layout:")
    print(f"  {target}/{WORKSPACE_TOML_FILENAME}    workspace metadata")
    print(f"  {target}/data/                 input data + cache.duckdb (created on first run)")
    print(f"  {target}/data/<variable>/      {len(VARIABLES)} folders, drop your files here")
    print(f"  {target}/projects/             one subfolder per project (work inside them)")
    print(f"  {target}/projects/{EXAMPLE_PROJECT_NAME}/     ready-to-run synthetic demo project")
    print()
    print("Each data/<variable>/ ships a README and one example file per accepted")
    print("format. Use the same naming for your files, e.g.:")
    print(f"  {target}/data/hydrometry/hydrometry_custom_LOC.csv")
    print(f"  {target}/data/geology/geology_custom_my_map.gpkg")
    print()
    print("You work inside projects/<name>/, never directly in projects/. Try the demo:")
    print(f"  hmp run {target}/projects/{EXAMPLE_PROJECT_NAME}/run_demo.toml")
    print()
    print(f"Workspace metadata: {result['workspace_toml']}")
