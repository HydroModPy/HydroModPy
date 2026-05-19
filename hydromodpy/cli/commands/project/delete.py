"""``hmp project delete`` - delete a project (catalog + Zarr + Parquet)."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from hydromodpy.cli.helpers import EXIT_NOT_FOUND, EXIT_USER_ABORT

NAME: str = "delete"
HELP: str = "Delete a project and its catalog data"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument("project", help="Project name (directory under projects/)")
    parser.add_argument(
        "--workspace",
        default=None,
        help="Workspace root (default: walk up from cwd, fallback ~/hydromodpy/)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip the confirmation prompt",
    )
    parser.set_defaults(_handler=run)
    return parser


def _resolve_workspace(workspace_arg: str | None) -> Path:
    import os

    from hydromodpy.cli.helpers import find_workspace_root
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
    project_dir = workspace_root / "projects" / args.project
    if not project_dir.is_dir():
        print(f"No such project: {project_dir}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    if not args.force:
        if not sys.stdin.isatty():
            print(
                "Refusing to delete without --force in non-interactive mode.",
                file=sys.stderr,
            )
            sys.exit(EXIT_USER_ABORT)
        try:
            resp = (
                input(f"Delete project {args.project!r} at {project_dir}? [y/N] ").strip().lower()
            )
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.", file=sys.stderr)
            sys.exit(EXIT_USER_ABORT)
        if resp not in {"y", "yes"}:
            print("Aborted.", file=sys.stderr)
            sys.exit(EXIT_USER_ABORT)

    bytes_freed = _path_size(project_dir)
    shutil.rmtree(project_dir)
    print(f"Deleted project {args.project} ({bytes_freed / 1e6:.2f} MB freed)")


def _path_size(path: Path) -> int:
    """Return the recursive file size of ``path`` in bytes."""
    if not path.exists():
        return 0
    total = 0
    try:
        for child in path.rglob("*"):
            try:
                if child.is_file():
                    total += int(child.stat().st_size)
            except OSError:
                continue
    except OSError:
        return total
    return total
