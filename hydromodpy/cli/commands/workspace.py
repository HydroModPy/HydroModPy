"""``hmp workspace`` - manage workspace-level runtime artifacts."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from hydromodpy.cli.helpers import EXIT_CONFIG, EXIT_NOT_FOUND, find_workspace_root

NAME: str = "workspace"
HELP: str = "Manage a HydroModPy workspace"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    commands = parser.add_subparsers(dest="workspace_command", required=True)

    clean = commands.add_parser(
        "clean",
        help="Remove generated workspace artifacts",
    )
    clean.add_argument("--workspace", default=None, help="Workspace root")
    clean.add_argument("--all", action="store_true", help="Clean every generated artifact group")
    clean.add_argument(
        "--results", action="store_true", help="Remove hydromodpy.duckdb and simulations/"
    )
    clean.add_argument(
        "--data-cache", action="store_true", help="Remove data/cache.duckdb and data/blobs/"
    )
    clean.add_argument("--runtime", action="store_true", help="Remove .hmp/")
    clean.add_argument("--exports", action="store_true", help="Remove exports/")
    clean.add_argument(
        "--scratch", action="store_true", help="Remove project .solver_scratch/ folders"
    )
    clean.add_argument("--figures", action="store_true", help="Remove project figures/ folders")
    clean.add_argument("-y", "--yes", action="store_true", help="Delete without dry-run")

    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    command = getattr(args, "workspace_command", None)
    if command == "clean":
        _cmd_clean(args)
        return
    print("Usage: hmp workspace {clean} [options]", file=sys.stderr)
    sys.exit(EXIT_CONFIG)


def _cmd_clean(args: argparse.Namespace) -> None:
    workspace = _resolve_workspace(getattr(args, "workspace", None))
    groups = _selected_groups(args)
    if not groups:
        print("Select at least one cleanup group, or pass --all.", file=sys.stderr)
        sys.exit(EXIT_CONFIG)

    targets = _collect_targets(workspace, groups)
    existing = [target for target in targets if target.exists() or target.is_symlink()]

    if not existing:
        print(f"No generated artifacts found in {workspace}.")
        return

    action = "Deleting" if args.yes else "Dry-run, would delete"
    print(f"{action} {len(existing)} path(s) in {workspace}:")
    for target in existing:
        print(f"  {target}")

    if not args.yes:
        print("Re-run with --yes to delete.")
        return

    for target in existing:
        _remove_path(workspace, target)


def _resolve_workspace(workspace_arg: str | None) -> Path:
    start = Path(workspace_arg).expanduser().resolve() if workspace_arg else Path.cwd().resolve()
    workspace = find_workspace_root(start)
    if not workspace.exists():
        print(f"Workspace not found: {workspace}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)
    if not workspace.is_dir():
        print(f"Workspace is not a directory: {workspace}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)
    return workspace


def _selected_groups(args: argparse.Namespace) -> set[str]:
    if args.all:
        return {"results", "data_cache", "runtime", "exports", "scratch", "figures"}
    groups: set[str] = set()
    if args.results:
        groups.add("results")
    if args.data_cache:
        groups.add("data_cache")
    if args.runtime:
        groups.add("runtime")
    if args.exports:
        groups.add("exports")
    if args.scratch:
        groups.add("scratch")
    if args.figures:
        groups.add("figures")
    return groups


def _collect_targets(workspace: Path, groups: set[str]) -> list[Path]:
    targets: list[Path] = []
    if "results" in groups:
        targets.extend(
            [
                workspace / "hydromodpy.duckdb",
                workspace / "hydromodpy.duckdb.wal",
                workspace / "simulations",
            ]
        )
    if "data_cache" in groups:
        targets.extend(
            [
                workspace / "data" / "cache.duckdb",
                workspace / "data" / "cache.duckdb.wal",
                workspace / "data" / "blobs",
            ]
        )
    if "runtime" in groups:
        targets.append(workspace / ".hmp")
    if "exports" in groups:
        targets.append(workspace / "exports")
    if "scratch" in groups:
        targets.extend(sorted(workspace.glob("projects/*/.solver_scratch")))
        targets.append(workspace / ".solver_scratch")
    if "figures" in groups:
        targets.extend(sorted(workspace.glob("projects/*/figures")))
    return _unique_paths(targets)


def _unique_paths(paths: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    out: list[Path] = []
    for path in paths:
        resolved = path.resolve(strict=False)
        if resolved in seen:
            continue
        seen.add(resolved)
        out.append(path)
    return out


def _remove_path(workspace: Path, target: Path) -> None:
    resolved_workspace = workspace.resolve()
    resolved_target = target.resolve(strict=False)
    if resolved_target == resolved_workspace or resolved_workspace not in resolved_target.parents:
        raise ValueError(f"Refusing to delete path outside workspace: {target}")
    if target.is_symlink() or target.is_file():
        target.unlink()
        return
    if target.is_dir():
        shutil.rmtree(target)
