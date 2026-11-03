"""What each kind of failure exits with. The numbers are frozen by ``surface/exit_codes.tsv``."""

from __future__ import annotations

import importlib
import sys

import pytest


def _load_helpers():
    return importlib.import_module("hydromodpy.cli.helpers")


def _load_main_module():
    return importlib.import_module("hydromodpy.cli.main")


def _run(monkeypatch, argv: list[str]) -> int:
    module = _load_main_module()
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as exc_info:
        module.main()
    return int(exc_info.value.code or 0)


def test_exit_code_for_keyboard_interrupt() -> None:
    helpers = _load_helpers()
    assert helpers.exit_code_for(KeyboardInterrupt()) == helpers.EXIT_SIGINT


def test_exit_code_for_file_not_found() -> None:
    helpers = _load_helpers()
    assert helpers.exit_code_for(FileNotFoundError("nope")) == helpers.EXIT_NOT_FOUND


def test_run_missing_file_returns_not_found(monkeypatch, capsys) -> None:
    code = _run(monkeypatch, ["hmp", "run", "/nonexistent/config.toml"])
    assert code == 10
    err = capsys.readouterr().err
    assert "not found" in err.lower()


def test_run_unsupported_extension_returns_config(monkeypatch, tmp_path, capsys) -> None:
    bad = tmp_path / "config.xml"
    bad.write_text("<?xml version='1.0'?>\n")
    code = _run(monkeypatch, ["hmp", "run", str(bad)])
    assert code == 14
    err = capsys.readouterr().err
    assert "unsupported" in err.lower()


def test_show_missing_workspace_returns_not_found(monkeypatch, tmp_path, capsys) -> None:
    missing = tmp_path / "empty_ws"
    missing.mkdir()
    code = _run(monkeypatch, ["hmp", "catalog", "show", "abcd", "--workspace", str(missing)])
    assert code == 10


def test_compare_missing_workspace_returns_not_found(monkeypatch, tmp_path) -> None:
    missing = tmp_path / "empty_ws"
    missing.mkdir()
    code = _run(
        monkeypatch,
        ["hmp", "report", "compare", "sim_a", "sim_b", "--workspace", str(missing)],
    )
    assert code == 10


def test_import_missing_publication_returns_not_found(monkeypatch, tmp_path) -> None:
    code = _run(
        monkeypatch,
        ["hmp", "catalog", "import", str(tmp_path / "no_such.tar"), "-w", str(tmp_path)],
    )
    assert code == 10


def test_exit_code_for_calibration_error() -> None:
    """A calibration failure has its own code, not the generic one."""
    from hydromodpy.core.exceptions import CalibrationError, ObjectiveError, OptimizerError

    helpers = _load_helpers()
    assert helpers.exit_code_for(CalibrationError("no root")) == helpers.EXIT_CALIBRATION
    # The two subclasses land on the same code rather than falling through to
    # the generic one, which is what used to happen.
    assert helpers.exit_code_for(ObjectiveError("x")) == helpers.EXIT_CALIBRATION
    assert helpers.exit_code_for(OptimizerError("x")) == helpers.EXIT_CALIBRATION


def test_a_solver_error_is_not_a_calibration_error() -> None:
    from hydromodpy.core.exceptions import SolverError

    helpers = _load_helpers()
    assert helpers.exit_code_for(SolverError("diverged")) == helpers.EXIT_SOLVER_ERROR
