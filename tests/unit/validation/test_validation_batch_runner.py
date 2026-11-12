"""Discovery, filtering and command lines of the batch runner of the validation cases."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from validation_cases.run_cases import (
    ValidationCaseExecution,
    build_execution_report,
    build_parser,
    build_run_command,
    discover_validation_cases,
    filter_validation_cases,
)


def _write_case(case_dir: Path, *, regime: str, solvers: tuple[str, ...]):
    case_dir.mkdir(parents=True, exist_ok=True)
    metadata_lines = [
        f'regime = "{regime}"',
        f'default_solver = "{solvers[0]}"',
        "",
        "[config_files]",
    ]
    metadata_lines.extend(f'{solver} = "config_{solver}.toml"' for solver in solvers)
    (case_dir / "metadata.toml").write_text("\n".join(metadata_lines) + "\n", encoding="utf-8")
    (case_dir / "run_case.py").write_text("print('ok')\n", encoding="utf-8")


def two_cases(tmp_path):
    package_root = tmp_path / "validation_cases"
    analytical_root = package_root / "analytical"
    _write_case(
        analytical_root / "steady" / "case_steady_dual",
        regime="steady",
        solvers=("modflownwt", "modflow6", "modflow6_irregular_tri", "boussinesq"),
    )
    _write_case(
        analytical_root / "transient" / "case_transient_nwt",
        regime="transient",
        solvers=("modflownwt",),
    )
    return discover_validation_cases(package_root=package_root)


STEADY_DUAL = "validation_cases.analytical.steady.case_steady_dual.run_case"
TRANSIENT_NWT = "validation_cases.analytical.transient.case_transient_nwt.run_case"


def test_discover_validation_cases(tmp_path):
    discovered = two_cases(tmp_path)

    assert [case.module_name for case in discovered] == [STEADY_DUAL, TRANSIENT_NWT]


FILTERS = [
    pytest.param("modflow6", "both", [STEADY_DUAL], id="modflow6"),
    pytest.param("modflow6_irregular_tri", "both", [STEADY_DUAL], id="irregular tri"),
    pytest.param("boussinesq", "both", [STEADY_DUAL], id="boussinesq"),
    pytest.param("modflownwt", "transient", [TRANSIENT_NWT], id="nwt transient only"),
]


@pytest.mark.parametrize(("solver", "regime", "expected"), FILTERS)
def test_filter_validation_cases(tmp_path, solver, regime, expected):
    selected = filter_validation_cases(two_cases(tmp_path), solver=solver, regime=regime)

    assert [case.module_name for case in selected] == expected


COMMANDS = [
    pytest.param("modflow6", 321, True, "--show", id="show"),
    pytest.param("modflow6_irregular_tri", 654, False, "--no-show", id="irregular tri, no show"),
]


@pytest.mark.parametrize(("solver", "timeout", "show_plot", "show_flag"), COMMANDS)
def test_build_run_command(tmp_path, solver, timeout, show_plot, show_flag):
    case_dir = tmp_path / "validation_cases" / "analytical" / "steady" / "case_demo"
    _write_case(
        case_dir, regime="steady", solvers=("modflownwt", "modflow6", "modflow6_irregular_tri")
    )
    case = discover_validation_cases(package_root=tmp_path / "validation_cases")[0]

    command = build_run_command(
        case,
        python_executable=Path(sys.executable),
        solver=solver,
        timeout=timeout,
        show_plot=show_plot,
    )

    assert command == [
        str(Path(sys.executable)),
        str(case.run_case_path),
        "--solver",
        solver,
        "--timeout",
        str(timeout),
        show_flag,
    ]


def test_execution_report(tmp_path):
    case_dir = tmp_path / "validation_cases" / "analytical" / "steady" / "case_demo"
    _write_case(case_dir, regime="steady", solvers=("modflownwt", "modflow6"))
    case = discover_validation_cases(package_root=tmp_path / "validation_cases")[0]

    report = build_execution_report(
        solver="modflow6",
        regime="steady",
        show_plot=False,
        selected_cases=[case],
        executions=[
            ValidationCaseExecution(
                case=case,
                command=("python", str(case.run_case_path), "--solver", "modflow6"),
                returncode=0,
                duration_seconds=1.25,
            )
        ],
    )

    assert report["solver"] == "modflow6"
    assert report["regime"] == "steady"
    assert report["all_passed"] is True
    assert report["completed_case_count"] == 1
    assert report["failed_case_count"] == 0
    assert report["cases"][0]["module_name"] == case.module_name
    assert report["cases"][0]["duration_seconds"] == 1.25


def test_parser_accepts_irregular_tri_solver():
    parser = build_parser()

    args = parser.parse_args(["--solver", "modflow6_irregular_tri", "--list"])

    assert args.solver == "modflow6_irregular_tri"
