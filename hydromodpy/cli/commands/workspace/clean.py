"""``hmp workspace clean`` - remove what a workspace can rebuild, and trash its results.

``--results`` never deletes a run: every run and session of every project
moves to the ``trash/`` of its project (``hmp catalog restore`` brings one
back, ``hmp catalog gc`` frees the bytes and leaves a tombstone, so no name
is given twice), and the index, which is derived, is removed. The other
groups (``--data-cache``, ``--runtime``, ``--scratch``) remove caches.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from hydromodpy.cli.conventions import (
    confirm_parser,
    dry_run_parser,
    format_parser,
    workspace_parser,
)
from hydromodpy.cli.helpers import EXIT_CONFIG, refuse, resolve_workspace
from hydromodpy.cli.output import emit

NAME: str = "clean"
HELP: str = "Trash the results of a workspace and remove its rebuildable caches"

RESULTS_GROUP = "results"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[
            workspace_parser(),
            confirm_parser(
                help="Carry the plan out. Without it the verb prints the plan and changes nothing"
            ),
            dry_run_parser(),
            format_parser(),
        ],
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
        help="With --results: go past the pin and the stale attempt, and trash those runs too",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.workspace import CLEAN_GROUPS, clean_workspace

    selected = {RESULTS_GROUP, *CLEAN_GROUPS} if args.all_groups else set()
    for name in (RESULTS_GROUP, *CLEAN_GROUPS):
        if getattr(args, name, False):
            selected.add(name)
    if not selected:
        refuse("Select at least one cleanup group, or pass --all.", EXIT_CONFIG)
    applied = bool(args.yes) and not args.dry_run
    workspace = resolve_workspace(args.workspace)

    plan: list[Path] = []
    indexes: list[Path] = []
    if RESULTS_GROUP in selected:
        plan, indexes = _trash_results(workspace, applied=applied, force=args.force)

    others = selected - {RESULTS_GROUP}
    candidates: list[str] = []
    if others:
        try:
            candidates = clean_workspace(workspace, groups=others, dry_run=not applied)[
                "candidates"
            ]
        except ValueError as exc:
            refuse(str(exc), EXIT_CONFIG, cause=exc)

    def table() -> None:
        if RESULTS_GROUP in selected:
            _print_results(workspace, plan, indexes, applied=applied)
        if others and not candidates:
            print(f"No rebuildable artifact found in {workspace}.")
        elif others:
            label = "Deleting" if applied else "Dry-run, would delete"
            print(f"{label} {len(candidates)} path(s) in {workspace}:")
            for target in candidates:
                print(f"  {target}")
        if not applied:
            print("Re-run with --yes to apply.")

    emit(
        args,
        "workspace clean",
        {
            "workspace": workspace,
            "applied": applied,
            "results": plan,
            "indexes": indexes,
            "caches": candidates,
        },
        table=table,
    )


def _trash_results(workspace: Path, *, applied: bool, force: bool) -> tuple[list[Path], list[Path]]:
    """Move every run and session under ``workspace`` to its project trash; return what moves."""
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
    if applied:
        now = datetime.now(UTC)
        for project_root, rel_dir in plan:
            trash_run(project_root, rel_dir, now=now, force=force)
        for path in indexes:
            path.unlink()
    return [project_root / rel_dir for project_root, rel_dir in plan], indexes


def _print_results(
    workspace: Path, plan: list[Path], indexes: list[Path], *, applied: bool
) -> None:
    if not plan and not indexes:
        print(f"No run or session to trash in {workspace}.")
        return
    label = "Moving" if applied else "Dry-run, would move"
    print(f"{label} {len(plan)} run(s) and session(s) to the trash of their project:")
    for path in plan:
        print(f"  {path}")
    if indexes:
        verb = "removing" if applied else "would remove"
        print(f"and {verb} {len(indexes)} index file(s), rebuilt by 'hmp catalog reindex':")
        for path in indexes:
            print(f"  {path}")
