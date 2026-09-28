"""A calibration run ends on what it found and where to read it.

The end of ``hmp run`` on a calibration used to print the raw Python dict of
its phases, its protocol and every deviation, three screens of text. In normal
mode it now prints one line naming the file and the protocol, one line per
phase, and where the best runs, the sessions and the methods paragraph are.
``--verbose`` keeps the full dict.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

import hydromodpy
from hydromodpy.cli.commands import run as run_command
from hydromodpy.core.logging import set_verbosity


def _phase(
    tmp_path: Path,
    *,
    name: str,
    index: int,
    method: str,
    n: int,
    parameter: str,
    value: float,
    unit: str,
    interval: tuple[float, float],
    cost: float,
    metric: str,
    run_name: str,
    session: str,
) -> dict:
    return {
        "phase": name,
        "index": index,
        "report": {
            "method": method,
            "n_iterations": n,
            "best_objective": cost,
            "best_parameters": {parameter: value},
            "best_run_name": run_name,
            "session_dir": str(tmp_path / "sessions" / session),
            "workspace": str(tmp_path),
            "extra": {
                "parameter_units": {parameter: unit},
                "cost_metric": metric,
                "parameter_intervals": [
                    {"name": parameter, "lower": interval[0], "upper": interval[1]}
                ],
            },
        },
    }


def _staged_summary(tmp_path: Path) -> dict:
    root = "20260928-033825-bisection-099012a0"
    return {
        "root_session_id": "099012a0",
        "phases": [
            _phase(
                tmp_path,
                name="steady_conductivity",
                index=0,
                method="bisection",
                n=15,
                parameter="K",
                value=8.106887879884017e-05,
                unit="m/s",
                interval=(7.498942093324559e-05, 0.0001),
                cost=1.9645705145436807,
                metric="distance_gap",
                run_name="nancon_calibrated_steady_conductivity",
                session=root,
            ),
            _phase(
                tmp_path,
                name="transient_storage",
                index=1,
                method="scipy_nelder_mead",
                n=6,
                parameter="Sy",
                value=0.04530171177248819,
                unit="-",
                interval=(0.04183300132670378, 0.05173374598489012),
                cost=0.07444487299044622,
                metric="1 - nse_log",
                run_name="nancon_calibrated_transient_storage",
                session="20260928-034005-scipy_nelder_mead-870992ac",
            ),
        ],
        "protocol": {"name": "matching_hydrographic_network", "version": "1.2"},
        "methods_paragraph": "Hydraulic properties were calibrated with ...",
        "methods_path": str(tmp_path / "sessions" / root / "methods.md"),
    }


@pytest.mark.fast
def test_the_recap_names_the_file_the_phases_and_where_to_read_on(
    tmp_path, monkeypatch, capsys
) -> None:
    monkeypatch.chdir(tmp_path)

    run_command._print_calibration_recap(_staged_summary(tmp_path), Path("run_calibration.toml"))

    assert capsys.readouterr().err.splitlines() == [
        "Calibration run_calibration.toml done: protocol matching_hydrographic_network 1.2",
        "  1 steady_conductivity: bisection, 15 runs, K = 8.107e-05 m/s in [7.499e-05, 0.0001], "
        "cost 1.965 (distance_gap)",
        "  2 transient_storage: scipy_nelder_mead, 6 runs, Sy = 0.0453 in [0.04183, 0.05173], "
        "cost 0.07444 (1 - nse_log)",
        "  Best runs: runs/nancon_calibrated_steady_conductivity/figures, "
        "runs/nancon_calibrated_transient_storage/figures",
        "  Sessions: sessions/20260928-033825-bisection-099012a0, "
        "sessions/20260928-034005-scipy_nelder_mead-870992ac",
        "  Methods:   sessions/20260928-033825-bisection-099012a0/methods.md",
    ]


@pytest.mark.fast
def test_a_calibration_of_one_phase_reads_as_one_phase(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    report = _staged_summary(tmp_path)["phases"][0]["report"]

    run_command._print_calibration_recap(report, Path("calibrate_k.toml"))

    lines = capsys.readouterr().err.splitlines()
    assert lines[0] == "Calibration calibrate_k.toml done"
    assert lines[1].startswith("  1: bisection, 15 runs, K = 8.107e-05 m/s")
    assert lines[2] == "  Best runs: runs/nancon_calibrated_steady_conductivity/figures"
    assert lines[3] == "  Session:  sessions/20260928-033825-bisection-099012a0"
    assert len(lines) == 4


def _run_calibration_file(tmp_path: Path, monkeypatch, verbosity: str | None) -> None:
    config = tmp_path / "run_calibration.toml"
    config.write_text('[workflow]\nmode = "calibration"\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(hydromodpy, "run", lambda path: _staged_summary(tmp_path))
    args = argparse.Namespace(
        dry_run=False,
        no_lock=True,
        no_display=False,
        verbosity=verbosity,
        profile=None,
    )
    try:
        run_command._run_toml(config, args=args)
    finally:
        set_verbosity("normal")


def test_normal_mode_prints_the_recap_and_not_the_dict(tmp_path, monkeypatch, capsys) -> None:
    _run_calibration_file(tmp_path, monkeypatch, "normal")

    err = capsys.readouterr().err
    assert "Calibration run_calibration.toml done" in err
    assert "Workflow 'calibration' complete" not in err
    assert "methods_paragraph" not in err


def test_verbose_mode_keeps_the_full_dict(tmp_path, monkeypatch, capsys) -> None:
    _run_calibration_file(tmp_path, monkeypatch, "verbose")

    err = capsys.readouterr().err
    assert "Workflow 'calibration' complete: run_calibration.toml" in err
    assert "methods_paragraph: Hydraulic properties" in err
