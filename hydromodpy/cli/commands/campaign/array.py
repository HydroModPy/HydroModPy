"""``hmp campaign array`` - write the array job of the current plan for a scheduler.

Thin wrapper around :func:`hydromodpy.project.launch.slurm.write_slurm_array`.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from hydromodpy.cli.conventions import format_parser, verbosity_parser, workspace_parser
from hydromodpy.cli.environment import add_environment_arguments
from hydromodpy.cli.helpers import exit_code_for, refuse
from hydromodpy.cli.output import emit
from hydromodpy.core.state.layout import PROJECT_MARKER_FILENAME

NAME: str = "array"
HELP: str = "Write the array job of the current plan for a scheduler (SLURM)"

SCHEDULERS: tuple[str, ...] = ("slurm",)


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), format_parser(), verbosity_parser()],
        epilog=(
            "Examples:\n"
            "  hmp campaign array . --scheduler slurm\n"
            "  hmp campaign array . --scheduler slurm --partition normal --time 12:00:00\n"
            "\n"
            "Writes jobs/<stamp>-slurm/{prepare.sh, array.sh, cases.txt} once, from the\n"
            "plan written by `hmp project plan`. Not verified on a cluster yet."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "project",
        nargs="?",
        default=None,
        help="Project directory, or its project.toml (default: -w, else the current directory)",
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
    add_environment_arguments(parser)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli.environment import environment_flags_of
    from hydromodpy.project.launch.journal import job_stamp
    from hydromodpy.project.launch.slurm import write_slurm_array

    target = Path(args.project or args.workspace or ".")
    root = target.parent if target.name == PROJECT_MARKER_FILENAME else target
    try:
        job = write_slurm_array(
            root,
            stamp=job_stamp(),
            partition=args.partition,
            walltime=args.walltime,
            threads_per_case=args.threads_per_case,
            prepare_parallel=args.prepare_parallel,
            environment_flags=environment_flags_of(args),
        )
    except Exception as exc:  # noqa: BLE001 - mapped to a typed exit code below
        refuse(f"hmp campaign array: {exc}", exit_code_for(exc), cause=exc)

    def table() -> None:
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

    emit(
        args,
        "campaign array",
        {
            "directory": job.directory,
            "plan_hash": job.plan_hash,
            "n_cases": job.n_cases,
            "cases_txt": job.cases_txt,
            "prepare_sh": job.prepare_sh,
            "array_sh": job.array_sh,
            "cpus_per_task": job.cpus_per_task,
            "threads_per_case": job.threads_per_case,
            "max_solves": job.max_solves,
            "prepare_parallel": job.prepare_parallel,
        },
        table=table,
    )
