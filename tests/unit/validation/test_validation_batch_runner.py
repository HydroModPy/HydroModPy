from __future__ import annotations

from pathlib import Path

from validation_cases.run_cases import (
    build_run_command,
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
        solvers=("modflownwt", "modflow6"),
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

    transient_nwt_cases = filter_validation_cases(discovered, solver="modflownwt", regime="transient")
    assert [case.module_name for case in transient_nwt_cases] == [
        "validation_cases.analytical.transient.case_transient_nwt.run_case",
    ]


def test_build_run_command_includes_solver_timeout_and_show_flag(tmp_path: Path) -> None:
    case_dir = tmp_path / "validation_cases" / "analytical" / "steady" / "case_demo"
    _write_case(case_dir, regime="steady", solvers=("modflownwt", "modflow6"))
    case = discover_validation_cases(package_root=tmp_path / "validation_cases")[0]

    command = build_run_command(
        case,
        python_executable=Path("C:/Python/python.exe"),
        solver="modflow6",
        timeout=321,
        show_plot=True,
    )

    assert command == [
        "C:\\Python\\python.exe",
        str(case.run_case_path),
        "--solver",
        "modflow6",
        "--timeout",
        "321",
        "--show",
    ]
