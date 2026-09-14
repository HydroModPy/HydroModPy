"""``hmp catalog gc`` - the single workspace maintenance verb.

Plans by default; ``--apply`` enforces the retention policy, purges expired
trash, quarantines orphan stores, replays interrupted purges, marks stale
running runs failed, cleans orphan caches and tmp parquet, and compacts
DuckDB + Zarr (the absorbed ``vacuum``). Nothing is ever destroyed on the
spot: a run selected by the retention policy goes to the project trash
(reversible with ``hmp catalog restore``), and orphan stores and figures are
moved to ``<project>/.hmp/trash/<stamp>/``.
"""

from __future__ import annotations

import argparse
import sys

from hydromodpy.cli._conventions import format_parser
from hydromodpy.cli.helpers import EXIT_NOT_FOUND, EXIT_OK

NAME: str = "gc"
HELP: str = (
    "Maintenance: apply the retention policy, expire trash, quarantine orphan stores, "
    "replay purges, compact DuckDB + Zarr"
)


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
        raise argparse.ArgumentTypeError("at least one version per lineage must be kept")
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
    from hydromodpy.cli._workers.catalog import DEFAULT_KEEP_VERSIONS, PROTECTED_TAG

    parser = subparsers.add_parser(NAME, help=HELP, parents=[format_parser()])
    parser.add_argument(
        "-w",
        "--workspace",
        default=None,
        help="Workspace root or project directory (default: auto-detect from cwd)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Execute the plan and free resources (default: print the plan only)",
    )
    parser.add_argument(
        "--keep-versions",
        type=_keep_versions,
        default=DEFAULT_KEEP_VERSIONS,
        metavar="N|all",
        help=(
            f"Versions kept per run lineage; older ones go to the trash "
            f"(default: {DEFAULT_KEEP_VERSIONS}, 'all' disables the rule)"
        ),
    )
    parser.add_argument(
        "--max-age-days",
        type=_positive_days,
        default=None,
        metavar="DAYS",
        help="Also trash runs created more than DAYS ago (default: no age limit)",
    )
    parser.add_argument(
        "--purge-figures",
        action="store_true",
        help="Also quarantine the regenerable figures/ directory of each run",
    )
    parser.epilog = f"A run tagged '{PROTECTED_TAG}' is exempt from every retention rule."
    parser.set_defaults(_handler=run)
    return parser


def _describe(policy: dict) -> str:
    """Render the retention policy as one readable line."""
    keep = policy["keep_versions"]
    age = policy["max_age_days"]
    return ", ".join(
        (
            "every version kept" if keep is None else f"{keep} version(s) per lineage",
            "no age limit" if age is None else f"trashed after {age} day(s)",
            "figures swept" if policy["purge_figures"] else "figures kept",
            f"'{policy['protected_tag']}' exempt",
        )
    )


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.catalog import RetentionPolicy, gc

    # Safe by default: planner unless --apply (mirrors `audit prune`,
    # the inverse of the old destructive-by-default --dry-run opt-in).
    dry_run = not args.apply
    policy = RetentionPolicy(
        keep_versions=args.keep_versions,
        max_age_days=args.max_age_days,
        purge_figures=args.purge_figures,
    )
    try:
        result = gc(args.workspace, dry_run=dry_run, policy=policy)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    if args.format == "json":
        import json

        print(json.dumps(result, default=str))
        sys.exit(EXIT_OK)

    label = "[plan] " if dry_run else ""
    for key, items in result["plan"].items():
        print(f"{label}{key}: {len(items)} candidate(s)")
        for item in items:
            print(f"  - {item}")
        if key in ("orphan_stores", "regenerable_figures") and items:
            print("  (moved to <project>/.hmp/trash/<stamp>/, never deleted)")
        if key in ("superseded_runs", "expired_runs") and items:
            print("  (moved to the project trash, restorable with 'hmp catalog restore')")
    print()
    print(f"Retention policy: {_describe(result['policy'])}")
    if dry_run:
        print("\nPlan only. Re-run with --apply to execute.")
        sys.exit(EXIT_OK)
    print()
    print("Summary:")
    for key, value in result["summary"].items():
        print(f"  {key}: {value}")
    sys.exit(EXIT_OK)
