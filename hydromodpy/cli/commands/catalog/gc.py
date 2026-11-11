"""``hmp catalog gc`` - collect what a project no longer needs, and say what it weighs.

Says what it would do; ``-y`` carries the plan out. Every decision reads the
project tree (:mod:`hydromodpy.results.retention`): a run whose attempt
stopped beating is marked aborted, the versions beyond the retention window
and the runs past the age limit go to the trash, the scratch of dead runs and
the earlier attempts of sealed runs leave all but their outcome, the products
over the store cap leave, and the field store of kept trials older than
``--trial-fields-days`` leaves behind a ``purged.json``. The output gives the bytes of each category
and the weight of the project before and after.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from hydromodpy.cli.conventions import (
    confirm_parser,
    dry_run_parser,
    format_parser,
    verbosity_parser,
    workspace_parser,
)
from hydromodpy.cli.exit_codes import EXIT_NOT_FOUND, refuse
from hydromodpy.cli.output import emit
from hydromodpy.core.state.layout import project_roots_under
from hydromodpy.core.state.result_dirs import resolve_project_root
from hydromodpy.results.retention import (
    DEFAULT_KEEP_VERSIONS,
    DEFAULT_TRIAL_FIELDS_DAYS,
    TRASH_RETENTION_DAYS,
)

NAME: str = "gc"
HELP: str = (
    "Maintenance: measure the project, close dead attempts, trash old versions, purge fields"
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


def _trial_fields_days(value: str) -> int | None:
    """Parse ``--trial-fields-days``: a positive count, or ``never`` to disable."""
    if value.strip().lower() == "never":
        return None
    return _positive_days(value)


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
            f"removed {TRASH_RETENTION_DAYS} days after their deletion. The fields of a kept\n"
            f"trial leave after {DEFAULT_TRIAL_FIELDS_DAYS} days, all but the best.\n"
            "\n"
            "Examples:\n"
            "  hmp catalog gc\n"
            "  hmp catalog gc --dry-run --format json\n"
            "  hmp catalog gc --keep-versions 3 --max-age-days 180 -y\n"
            "  hmp catalog gc --trial-fields-days never -y"
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
    parser.add_argument(
        "--trial-fields-days",
        type=_trial_fields_days,
        default=DEFAULT_TRIAL_FIELDS_DAYS,
        metavar="DAYS|never",
        help=(
            "Remove the fields of kept trials older than DAYS, all but the best "
            f"(default: {DEFAULT_TRIAL_FIELDS_DAYS}, 'never' disables the rule)"
        ),
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.project.facade import open_project

    target = Path(args.workspace or Path.cwd()).expanduser().resolve()
    if not target.is_dir():
        refuse(f"{target} is not a directory.", EXIT_NOT_FOUND)
    applied = bool(args.yes) and not args.dry_run
    report: dict[str, dict] = {}
    for root in project_roots_under(resolve_project_root(target)):
        project = open_project(root)
        try:
            result = project.gc(
                dry_run=not applied,
                keep_versions=args.keep_versions,
                max_age_days=args.max_age_days,
                trial_fields_days=args.trial_fields_days,
            )
        finally:
            project.close()
        categories = result.plan.categories()
        report[str(root)] = {
            "applied": result.applied,
            "plan": categories,
            "bytes": {name: result.plan.bytes_of(name) for name in categories},
            "freed": dict(result.freed),
            "weight": {
                "before": result.before.as_dict(),
                "after": result.after.as_dict(),
                "total_before": result.before.total(),
                "total_after": result.after.total(),
            },
        }

    def table() -> None:
        label = "" if applied else "[plan] "
        for root, block in report.items():
            print(f"# {root}")
            for key, items in block["plan"].items():
                print(f"{label}{key}: {len(items)} ({block['bytes'][key]} bytes)")
                for item in items:
                    print(f"  - {item}")
            weight = block["weight"]
            print(
                f"\nWeight: {weight['total_before']} bytes before, "
                f"{weight['total_after']} bytes after."
            )
        keep = "every version" if args.keep_versions is None else args.keep_versions
        age = "no age limit" if args.max_age_days is None else f"{args.max_age_days} days"
        fields = (
            "kept trials keep their fields"
            if args.trial_fields_days is None
            else f"{args.trial_fields_days} days"
        )
        print(
            f"\nRetention: {keep} kept per name, {age}, trial fields {fields}, "
            f"trash kept {TRASH_RETENTION_DAYS} days."
        )
        if not applied:
            print("Plan only. Re-run with -y to carry it out.")

    emit(
        args,
        "catalog gc",
        {
            "applied": applied,
            "keep_versions": args.keep_versions,
            "max_age_days": args.max_age_days,
            "trial_fields_days": args.trial_fields_days,
            "projects": report,
        },
        table=table,
    )
