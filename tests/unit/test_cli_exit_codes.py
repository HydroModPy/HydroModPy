"""Standardised exit codes for the HydroModPy CLI.

Contract (see ``reports/99_target_architecture.md`` §5.3):

- 0   success
- 1   generic untyped error
- 2   argparse usage error
- 10  not found (file, sim_id, workspace)
- 11  schema mismatch
- 12  write conflict
- 13  read-only handle
- 14  config / Pydantic error
- 15  solver error
- 16  validation error (pandera, CRS, range)
- 17  cross-project error
- 18  backup failed
- 19  migration failed
- 130 SIGINT (POSIX KeyboardInterrupt)
"""

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


def test_exit_code_constants_exposed() -> None:
    helpers = _load_helpers()
    assert helpers.EXIT_OK == 0
    assert helpers.EXIT_GENERIC == 1
    assert helpers.EXIT_USAGE == 2
    assert helpers.EXIT_NOT_FOUND == 10
    assert helpers.EXIT_SCHEMA_MISMATCH == 11
    assert helpers.EXIT_WRITE_CONFLICT == 12
    assert helpers.EXIT_READ_ONLY == 13
    assert helpers.EXIT_CONFIG == 14
    assert helpers.EXIT_SOLVER_ERROR == 15
    assert helpers.EXIT_VALIDATION == 16
    assert helpers.EXIT_CROSS_PROJECTS == 17
    assert helpers.EXIT_BACKUP_FAILED == 18
    assert helpers.EXIT_MIGRATION_FAILED == 19
    assert helpers.EXIT_SIGINT == 130


def test_legacy_aliases_point_to_typed_codes() -> None:
    helpers = _load_helpers()
    assert helpers.EXIT_RUN_FAILED == helpers.EXIT_GENERIC
    assert helpers.EXIT_USER_ABORT == helpers.EXIT_SIGINT
    assert helpers.EXIT_DATA_ERROR == helpers.EXIT_VALIDATION


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
        ["hmp", "compare", "sim_a", "sim_b", "--workspace", str(missing)],
    )
    assert code == 10


def test_import_missing_package_returns_not_found(monkeypatch, tmp_path) -> None:
    code = _run(
        monkeypatch,
        ["hmp", "import", str(tmp_path / "no_such.hmp"), "-w", str(tmp_path)],
    )
    assert code == 10
