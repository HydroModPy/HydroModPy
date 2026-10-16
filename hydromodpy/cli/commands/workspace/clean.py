"""``hmp workspace clean`` - remove what a workspace can rebuild, and trash its results.

``--results`` never deletes a run: every run and session of every project
moves to the ``trash/`` of its project (``hmp catalog restore`` brings one
back, ``hmp catalog gc`` frees the bytes and leaves a tombstone, so no name
is given twice), and the index, which is derived, is removed. The other
groups (``--data-cache``, ``--runtime``, ``--scratch``) remove caches.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from hydromodpy.cli._conventions import workspace_parser
from hydromodpy.cli.helpers import EXIT_CONFIG, EXIT_NOT_FOUND, exit_code_for, resolve_workspace

NAME: str = "clean"
HELP: str = "Trash the results of a workspace and remove its rebuildable caches"

RESULTS_GROUP = "results"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser()],
        epilog="Examples:\n  hmp workspace clean --results --dry-run\n  hmp workspace clean --all -y",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--all", action="store_true", dest="all_groups", help="Clean every group below"
    )
    parser.add_argument(
        "--results",
        action="store_true",
        help="Move every run and session to the trash of its project, remove the index",
    )
    parser.add_argument(
        "--data-cache", action="store_true", dest="data_cache", help="The data cache"
    )
    parser.add_argument("--runtime", action="store_true", help="The .hmp/ runtime folder")
    parser.add_argument("--scratch", action="store_true", help="The scratch folders (.hmp/scratch)")
    parser.add_argument(
        "--force",
        action="store_true",
        help="With --results: trash pinned runs and attempts that stopped beating too",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="List what would be removed and remove nothing (the default unless -y is given)",
    )
    parser.add_argument("-y", "--yes", action="store_true", help="Delete without dry-run")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.workspace import CLEAN_GROUPS, clean_workspace

    selected = {RESULTS_GROUP, *CLEAN_GROUPS} if args.all_groups else set()
    for name in (RESULTS_GROUP, *CLEAN_GROUPS):
        if getattr(args, name, False):
            selected.add(name)
    if not selected:
        print("Select at least one cleanup group, or pass --all.", file=sys.stderr)
        sys.exit(EXIT_CONFIG)
    dry_run = bool(args.dry_run) or not args.yes
    workspace = resolve_workspace(args.workspace)

    if RESULTS_GROUP in selected:
        try:
            _trash_results(workspace, dry_run=dry_run, force=args.force)
        except Exception as exc:  # noqa: BLE001 - map in-use, protected and IO errors
            print(str(exc), file=sys.stderr)
            sys.exit(exit_code_for(exc))

    others = selected - {RESULTS_GROUP}
    if others:
        try:
            result = clean_workspace(workspace, groups=others, dry_run=dry_run)
        except FileNotFoundError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(EXIT_NOT_FOUND)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(EXIT_CONFIG)
        candidates = result["candidates"]
        if not candidates:
            print(f"No rebuildable artifact found in {result['workspace']}.")
        else:
            label = "Dry-run, would delete" if dry_run else "Deleting"
            print(f"{label} {len(candidates)} path(s) in {result['workspace']}:")
            for target in candidates:
                print(f"  {target}")
    if dry_run:
        print("Re-run with --yes to apply.")


def _trash_results(workspace: Path, *, dry_run: bool, force: bool) -> None:
    """Move every run and session under ``workspace`` to its project trash."""
    from hydromodpy.core.state.paths import CATALOG_FILENAME, catalog_path_for, project_roots_under
    from hydromodpy.results.catalog.indexer import scan_tree
    from hydromodpy.results.trash import (
        PROTECTED_TAG,
        ProtectedDirectoryError,
        check_not_running,
        is_protected,
        trash_run,
    )

    plan: list[tuple[Path, str]] = []
    indexes: list[Path] = []
    for project_root in project_roots_under(workspace):
        for entry in scan_tree(project_root).values():
            if entry.kind == "trial":
                continue
            check_not_running(entry.path, entry.rel_dir, force=force)
            if not force and is_protected(entry.path):
                raise ProtectedDirectoryError(
                    f"{project_root.name}/{entry.rel_dir} is tagged '{PROTECTED_TAG}'; "
                    "pass --force to trash it."
                )
            plan.append((project_root, entry.rel_dir))
        index = catalog_path_for(project_root)
        indexes.extend(
            path for path in (index, index.with_name(f"{CATALOG_FILENAME}.wal")) if path.is_file()
        )

    if not plan and not indexes:
        print(f"No run or session to trash in {workspace}.")
        return
    label = "Dry-run, would move" if dry_run else "Moving"
    print(f"{label} {len(plan)} run(s) and session(s) to the trash of their project:")
    for project_root, rel_dir in plan:
        print(f"  {project_root / rel_dir}")
    if indexes:
        verb = "would remove" if dry_run else "removing"
        print(f"and {verb} {len(indexes)} index file(s), rebuilt by 'hmp catalog reindex':")
        for path in indexes:
            print(f"  {path}")
    if dry_run:
        return
    now = datetime.now(UTC)
    for project_root, rel_dir in plan:
        trash_run(project_root, rel_dir, now=now, force=force)
    for path in indexes:
        path.unlink()
