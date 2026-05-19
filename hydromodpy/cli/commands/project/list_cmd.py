"""``hmp project list`` - list projects in the workspace."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from hydromodpy.cli.helpers import EXIT_NOT_FOUND, find_workspace_root
from hydromodpy.core.state.paths import PROJECT_TOML_FILENAME

NAME: str = "list"
HELP: str = "List projects available in a workspace"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument(
        "--workspace",
        default=None,
        help="Workspace root (default: walk up from cwd, fallback ~/hydromodpy/)",
    )
    parser.set_defaults(_handler=run)
    return parser


def _resolve_workspace(workspace_arg: str | None) -> Path:
    """Resolve the workspace root, mirroring ``hmp display --list``."""
    from hydromodpy.data.scaffold import DEFAULT_ROOT

    if workspace_arg:
        return Path(workspace_arg).expanduser().resolve()

    ws_override = os.environ.get("HMP_WORKSPACE")
    start = Path(ws_override).expanduser().resolve() if ws_override else Path.cwd()
    found = find_workspace_root(start)
    if (found / "projects").is_dir() or (found / "data").is_dir():
        return found
    return Path(DEFAULT_ROOT).expanduser().resolve()


def run(args: argparse.Namespace) -> None:
    workspace_root = _resolve_workspace(args.workspace)
    projects_dir = workspace_root / "projects"

    print(f"# workspace: {workspace_root}")

    if not projects_dir.is_dir():
        print(
            f"No projects/ directory found in {workspace_root}",
            file=sys.stderr,
        )
        sys.exit(EXIT_NOT_FOUND)

    print("# projects/:")
    for project_dir in sorted(projects_dir.iterdir()):
        if not project_dir.is_dir():
            continue
        has_project_toml = (project_dir / PROJECT_TOML_FILENAME).exists()
        run_tomls = list(project_dir.glob("run_*.toml"))
        details = []
        if has_project_toml:
            details.append(PROJECT_TOML_FILENAME)
        if run_tomls:
            details.append(f"{len(run_tomls)} run(s)")
        suffix = f"  [{', '.join(details)}]" if details else ""
        print(f"  {project_dir.name}{suffix}")
