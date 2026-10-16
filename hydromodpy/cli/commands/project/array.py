"""``hmp project array`` - write the array job of the current plan for a scheduler.

Thin wrapper around :func:`hydromodpy.project.launch.slurm.write_slurm_array`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli._conventions import verbosity_parser
from hydromodpy.cli.helpers import apply_verbosity, exit_code_for
from hydromodpy.core.state.paths import PROJECT_MARKER_FILENAME

NAME: str = "array"
HELP: str = "Write the array job of the current plan for a scheduler (SLURM)"

SCHEDULERS: tuple[str, ...] = ("slurm",)


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[verbosity_parser()],
        epilog=(
            "Examples:\n"
            "  hmp project array . --scheduler slurm\n"
            "  hmp project array . --scheduler slurm --partition normal --time 12:00:00\n"
            "\n"
            "Writes jobs/<stamp>-slurm/{prepare.sh, array.sh, cases.txt} once, from the\n"
            "plan written by `hmp project plan`. Not verified on a cluster yet."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "project",
        nargs="?",
        default=".",
        help="Project directory, or its project.toml (default: current directory)",
    )
    parser.add_argument(
        "--scheduler",
        required=True,
        choices=SCHEDULERS,
        help="Scheduler the job scripts are written for",
    )
    parser.add_argument("--partition", default=None, help="SLURM partition of both arrays")
    parser.add_argument(
        "--time",
        dest="walltime",
        default=None,
        metavar="WALLTIME",
        help="Walltime of one task (M, H:M:S, D-H:M:S); longer than the 600 s warning",
    )
    parser.add_argument(
        "--threads-per-case",
        type=int,
        default=None,
        help="Threads of one case (default: [sites.run] threads_per_case)",
    )
    parser.add_argument(
        "--prepare-parallel",
        type=int,
        default=None,
        help="Cases prepared side by side (default: [sites.run] prepare_parallel)",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    apply_verbosity(args, {})
    from hydromodpy.project.launch.journal import job_stamp
    from hydromodpy.project.launch.slurm import write_slurm_array

    target = Path(args.project)
    root = target.parent if target.name == PROJECT_MARKER_FILENAME else target
    try:
        job = write_slurm_array(
            root,
            stamp=job_stamp(),
            partition=args.partition,
            walltime=args.walltime,
            threads_per_case=args.threads_per_case,
            prepare_parallel=args.prepare_parallel,
        )
    except Exception as exc:  # noqa: BLE001 - mapped to a typed exit code below
        print(f"hmp project array: {exc}", file=sys.stderr)
        sys.exit(exit_code_for(exc))

    print(f"Wrote {job.directory} from plan {job.plan_hash}:")
    print(f"  {job.cases_txt.name:<11} {job.n_cases} case(s), line N for task N")
    print(
        f"  {job.prepare_sh.name:<11} geography and data (--until load_data), "
        f"{job.prepare_parallel} side by side, writes hydromodpy.lock at the end"
    )
    print(
        f"  {job.array_sh.name:<11} the solves, {job.cpus_per_task} cpu(s) per task "
        f"({job.threads_per_case} thread(s) x {job.max_solves} solve(s))"
    )
    print("Submit:")
    print(f"  prep=$(sbatch --parsable {job.prepare_sh})")
    print(f"  sbatch --dependency=afterok:$prep {job.array_sh}")
    print("Not verified on a cluster yet.")
