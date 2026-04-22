from __future__ import annotations

from pathlib import Path
import sys

from validation_cases.run_cases import (
    ValidationCaseExecution,
    build_parser,
    build_run_command,
    build_execution_report,
    discover_validation_cases,
    filter_validation_cases,
)


def _write_case(case_dir: Path, *, regime: str, solvers: tuple[str, ...]) -> None:
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


def test_discover_and_filter_validation_cases(tmp_path: Path) -> None:
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

    discovered = discover_validation_cases(package_root=package_root)

    assert [case.module_name for case in discovered] == [
        "validation_cases.analytical.steady.case_steady_dual.run_case",
        "validation_cases.analytical.transient.case_transient_nwt.run_case",
    ]

    modflow6_cases = filter_validation_cases(discovered, solver="modflow6", regime="both")
    assert [case.module_name for case in modflow6_cases] == [
        "validation_cases.analytical.steady.case_steady_dual.run_case",
    ]

    modflow6_irregular_cases = filter_validation_cases(
        discovered,
        solver="modflow6_irregular_tri",
        regime="both",
    )
    assert [case.module_name for case in modflow6_irregular_cases] == [
        "validation_cases.analytical.steady.case_steady_dual.run_case",
    ]

    boussinesq_cases = filter_validation_cases(discovered, solver="boussinesq", regime="both")
    assert [case.module_name for case in boussinesq_cases] == [
        "validation_cases.analytical.steady.case_steady_dual.run_case",
    ]

    transient_nwt_cases = filter_validation_cases(
        discovered, solver="modflownwt", regime="transient"
    )
    assert [case.module_name for case in transient_nwt_cases] == [
        "validation_cases.analytical.transient.case_transient_nwt.run_case",
    ]


def test_build_run_command_includes_solver_timeout_and_show_flag(tmp_path: Path) -> None:
    case_dir = tmp_path / "validation_cases" / "analytical" / "steady" / "case_demo"
    _write_case(
        case_dir,
        regime="steady",
        solvers=("modflownwt", "modflow6", "modflow6_irregular_tri"),
    )
    case = discover_validation_cases(package_root=tmp_path / "validation_cases")[0]

    command = build_run_command(
        case,
        python_executable=Path(sys.executable),
        solver="modflow6",
        timeout=321,
        show_plot=True,
    )

    assert command == [
        str(Path(sys.executable)),
        str(case.run_case_path),
        "--solver",
        "modflow6",
        "--timeout",
        "321",
        "--show",
    ]


def test_build_run_command_supports_modflow6_irregular_tri(tmp_path: Path) -> None:
    case_dir = tmp_path / "validation_cases" / "analytical" / "steady" / "case_demo"
    _write_case(
        case_dir,
        regime="steady",
        solvers=("modflownwt", "modflow6", "modflow6_irregular_tri"),
    )
    case = discover_validation_cases(package_root=tmp_path / "validation_cases")[0]

    command = build_run_command(
        case,
        python_executable=Path(sys.executable),
        solver="modflow6_irregular_tri",
        timeout=654,
        show_plot=False,
    )

    assert command == [
        str(Path(sys.executable)),
        str(case.run_case_path),
        "--solver",
        "modflow6_irregular_tri",
        "--timeout",
        "654",
        "--no-show",
    ]


def test_build_execution_report_summarizes_case_runs(tmp_path: Path) -> None:
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


def test_build_parser_accepts_modflow6_irregular_tri_solver() -> None:
    parser = build_parser()

    args = parser.parse_args(["--solver", "modflow6_irregular_tri", "--list"])

    assert args.solver == "modflow6_irregular_tri"
