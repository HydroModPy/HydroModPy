"""``hmp catalog gc`` - collect the runs and trash entries a project no longer needs.

Says what it would do; ``-y`` carries the plan out. Every decision reads the
project tree (:mod:`hydromodpy.results.retention`): a run whose attempt
stopped beating is marked aborted, the versions beyond the retention window
and the runs past the age limit go to the trash, and the trash entries older
than the trash retention are removed, each leaving a tombstone.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from hydromodpy.cli.conventions import (
    confirm_parser,
    dry_run_parser,
    format_parser,
    verbosity_parser,
    workspace_parser,
)
from hydromodpy.cli.helpers import EXIT_NOT_FOUND, apply_verbosity, refuse
from hydromodpy.cli.output import emit
from hydromodpy.core.state.paths import (
    catalog_path_for,
    project_roots_under,
    resolve_project_root,
)
from hydromodpy.results.retention import DEFAULT_KEEP_VERSIONS, TRASH_RETENTION_DAYS

NAME: str = "gc"
HELP: str = "Maintenance: mark dead attempts aborted, trash old versions, remove expired trash"


def _keep_versions(value: str) -> int | None:
    """Parse ``--keep-versions``: a positive count, or ``all`` to disable."""
    if value.strip().lower() == "all":
        return None
    try:
        count = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"expected a positive integer or 'all', got {value!r}"
        ) from exc
    if count < 1:
        raise argparse.ArgumentTypeError("at least one version per name must be kept")
    return count


def _positive_days(value: str) -> int:
    """Parse a day count that must be at least one."""
    try:
        days = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected a positive integer, got {value!r}") from exc
    if days < 1:
        raise argparse.ArgumentTypeError("the age limit must be at least one day")
    return days


def register(subparsers) -> argparse.ArgumentParser:
    from hydromodpy.results.trash import PROTECTED_TAG

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
            verbosity_parser(),
        ],
        epilog=(
            f"A directory tagged '{PROTECTED_TAG}' is never collected. Trash entries are\n"
            f"removed {TRASH_RETENTION_DAYS} days after their deletion.\n"
            "\n"
            "Examples:\n"
            "  hmp catalog gc\n"
            "  hmp catalog gc --dry-run --format json\n"
            "  hmp catalog gc --keep-versions 3 --max-age-days 180 -y"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--keep-versions",
        type=_keep_versions,
        default=DEFAULT_KEEP_VERSIONS,
        metavar="N|all",
        help=(
            f"Versions kept per run name; older ones go to the trash "
            f"(default: {DEFAULT_KEEP_VERSIONS}, 'all' disables the rule)"
        ),
    )
    parser.add_argument(
        "--max-age-days",
        type=_positive_days,
        default=None,
        metavar="DAYS",
        help="Also trash runs started more than DAYS ago (default: no age limit)",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    apply_verbosity(args, {})
    from hydromodpy.results.retention import RetentionPolicy, apply_gc, plan_gc

    target = Path(args.workspace or Path.cwd()).expanduser().resolve()
    if not target.is_dir():
        refuse(f"{target} is not a directory.", EXIT_NOT_FOUND)
    applied = bool(args.yes) and not args.dry_run
    policy = RetentionPolicy(keep_versions=args.keep_versions, max_age_days=args.max_age_days)
    now = datetime.now(UTC)
    report: dict[str, dict] = {}
    for root in project_roots_under(resolve_project_root(target)):
        plan = plan_gc(root, policy, now=now)
        summary = apply_gc(plan, now=now) if applied else {}
        if applied and catalog_path_for(root).is_file():
            from hydromodpy.results.catalog.indexer import index_new_runs

            index_new_runs(root)
        report[str(root)] = {"plan": plan.categories(), "summary": summary}

    def table() -> None:
        label = "" if applied else "[plan] "
        for root, block in report.items():
            print(f"# {root}")
            for key, items in block["plan"].items():
                print(f"{label}{key}: {len(items)}")
                for item in items:
                    print(f"  - {item}")
        keep = "every version" if policy.keep_versions is None else policy.keep_versions
        age = "no age limit" if policy.max_age_days is None else f"{policy.max_age_days} days"
        print(f"\nRetention: {keep} kept per name, {age}, trash kept {TRASH_RETENTION_DAYS} days.")
        if not applied:
            print("Plan only. Re-run with -y to carry it out.")

    emit(
        args,
        "catalog gc",
        {
            "applied": applied,
            "keep_versions": policy.keep_versions,
            "max_age_days": policy.max_age_days,
            "projects": report,
        },
        table=table,
    )
