"""Refresh committed validation batch reports for the analytical inventory."""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_DIR = REPO_ROOT / "validation_cases" / "reports" / "latest"
DEFAULT_SOLVERS = ("modflownwt", "modflow6", "modflow6_irregular_tri", "boussinesq")


@dataclass(frozen=True, slots=True)
class ValidationReportJob:
    """One committed batch-report refresh target."""

    solver: str
    regime: str
    show_plot: bool
    timeout: int
    report_path: Path


def build_report_jobs(
    *,
    output_dir: Path = DEFAULT_REPORT_DIR,
    solvers: tuple[str, ...] = DEFAULT_SOLVERS,
    regime: str = "both",
    show_plot: bool = False,
    timeout: int = 1800,
) -> tuple[ValidationReportJob, ...]:
    """Return the ordered report-refresh jobs implied by one CLI configuration."""

    resolved_output_dir = Path(output_dir).expanduser().resolve()
    return tuple(
        ValidationReportJob(
            solver=str(solver),
            regime=str(regime),
            show_plot=bool(show_plot),
            timeout=int(timeout),
            report_path=resolved_output_dir / f"{solver}_{regime}.json",
        )
        for solver in solvers
    )


def build_run_cases_command(
    job: ValidationReportJob,
    *,
    python_executable: Path,
    stop_on_error: bool,
) -> list[str]:
    """Build the underlying ``validation_cases.run_cases`` command for one job."""

    command = [
        str(Path(python_executable)),
        "-m",
        "validation_cases.run_cases",
        "--solver",
        str(job.solver),
        "--regime",
        str(job.regime),
        "--timeout",
        str(int(job.timeout)),
        "--show" if bool(job.show_plot) else "--no-show",
        "--report-json",
        str(job.report_path),
    ]
    if bool(stop_on_error):
        command.append("--stop-on-error")
    return command


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser for the report refresh helper."""

    parser = argparse.ArgumentParser(
        description="Refresh committed JSON reports for the analytical validation inventory."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_REPORT_DIR,
        help="Directory that receives one <solver>_<regime>.json file per requested solver.",
    )
    parser.add_argument(
        "--regime",
        choices=("steady", "transient", "both"),
        default="both",
        help="Subset of the analytical inventory forwarded to validation_cases.run_cases.",
    )
    parser.add_argument(
        "--python",
        type=Path,
        default=Path(sys.executable),
        help="Python executable used to call validation_cases.run_cases.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=1800,
        help="Per-case timeout forwarded to validation_cases.run_cases.",
    )
    parser.add_argument(
        "--solvers",
        nargs="+",
        choices=DEFAULT_SOLVERS,
        default=list(DEFAULT_SOLVERS),
        help="Solver reports to refresh. Defaults to all supported analytical solver families.",
    )
    parser.set_defaults(show_plot=False, stop_on_error=False)
    parser.add_argument(
        "--show",
        dest="show_plot",
        action="store_true",
        help="Open diagnostic figures while refreshing reports.",
    )
    parser.add_argument(
        "--no-show",
        dest="show_plot",
        action="store_false",
        help="Disable interactive figures while refreshing reports.",
    )
    parser.add_argument(
        "--stop-on-error",
        action="store_true",
        help="Stop the refresh sequence after the first failing solver batch.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Print the planned refresh commands without executing them.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for the committed validation-report refresh helper."""

    args = build_parser().parse_args(argv)
    jobs = build_report_jobs(
        output_dir=Path(args.output_dir),
        solvers=tuple(str(solver) for solver in args.solvers),
        regime=str(args.regime),
        show_plot=bool(args.show_plot),
        timeout=int(args.timeout),
    )
    if not jobs:
        raise SystemExit("No solver job selected.")

    failed_jobs: list[ValidationReportJob] = []
    for job in jobs:
        command = build_run_cases_command(
            job,
            python_executable=Path(args.python),
            stop_on_error=bool(args.stop_on_error),
        )
        print(f"[{job.solver}] {job.report_path}")
        print(" ".join(command))
        if args.list:
            continue
        completed = subprocess.run(command, cwd=REPO_ROOT, check=False)
        if int(completed.returncode) != 0:
            failed_jobs.append(job)
            if bool(args.stop_on_error):
                break

    if failed_jobs:
        print("")
        print("Failed report refresh jobs:")
        for job in failed_jobs:
            print(f"- {job.solver} -> {job.report_path}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
