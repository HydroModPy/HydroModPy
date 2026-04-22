from __future__ import annotations

import sys
from pathlib import Path

from validation_cases.update_reports import (
    DEFAULT_SOLVERS,
    build_parser,
    build_report_jobs,
    build_run_cases_command,
)


def test_build_report_jobs_targets_one_json_per_solver(tmp_path: Path) -> None:
    jobs = build_report_jobs(
        output_dir=tmp_path / "reports",
        solvers=("modflow6", "modflow6_irregular_tri", "boussinesq"),
        regime="both",
        show_plot=False,
        timeout=4321,
    )

    assert [job.solver for job in jobs] == [
        "modflow6",
        "modflow6_irregular_tri",
        "boussinesq",
    ]
    assert all(job.regime == "both" for job in jobs)
    assert all(job.show_plot is False for job in jobs)
    assert all(job.timeout == 4321 for job in jobs)
    assert jobs[0].report_path == (tmp_path / "reports" / "modflow6_both.json").resolve()
    assert (
        jobs[1].report_path == (tmp_path / "reports" / "modflow6_irregular_tri_both.json").resolve()
    )
    assert jobs[2].report_path == (tmp_path / "reports" / "boussinesq_both.json").resolve()


def test_build_run_cases_command_wraps_validation_batch_runner(tmp_path: Path) -> None:
    job = build_report_jobs(
        output_dir=tmp_path / "reports",
        solvers=("modflow6_irregular_tri",),
        regime="steady",
        show_plot=True,
        timeout=321,
    )[0]

    command = build_run_cases_command(
        job,
        python_executable=Path(sys.executable),
        stop_on_error=True,
    )

    assert command == [
        str(Path(sys.executable)),
        "-m",
        "validation_cases.run_cases",
        "--solver",
        "modflow6_irregular_tri",
        "--regime",
        "steady",
        "--timeout",
        "321",
        "--show",
        "--report-json",
        str((tmp_path / "reports" / "modflow6_irregular_tri_steady.json").resolve()),
        "--stop-on-error",
    ]


def test_default_report_jobs_include_modflow6_irregular_tri(tmp_path: Path) -> None:
    jobs = build_report_jobs(output_dir=tmp_path / "reports")

    assert tuple(job.solver for job in jobs) == DEFAULT_SOLVERS


def test_build_parser_accepts_modflow6_irregular_tri_solver_choice() -> None:
    parser = build_parser()

    args = parser.parse_args(["--solvers", "modflow6_irregular_tri", "--list"])

    assert args.solvers == ["modflow6_irregular_tri"]
