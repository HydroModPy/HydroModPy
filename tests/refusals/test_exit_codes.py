"""What each kind of failure exits with. The numbers are frozen by ``surface/exit_codes.tsv``."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


def _load_helpers():
    return importlib.import_module("hydromodpy.cli.exit_codes")


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
    code = _run(monkeypatch, ["hmp", "show", "abcd", "--workspace", str(missing)])
    assert code == 10


def test_diff_missing_workspace_returns_not_found(monkeypatch, tmp_path) -> None:
    missing = tmp_path / "empty_ws"
    missing.mkdir()
    code = _run(
        monkeypatch,
        ["hmp", "diff", "sim_a", "sim_b", "--workspace", str(missing)],
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


SURFACE = Path(__file__).parents[1] / "unit" / "architecture" / "surface" / "exit_codes.tsv"


def _registered() -> list[tuple[str, int]]:
    rows = [line.split("\t") for line in SURFACE.read_text(encoding="utf-8").splitlines()]
    return [(name, int(code)) for name, code in rows if not name.startswith("EXIT_")]


@pytest.mark.parametrize(("name", "code"), _registered(), ids=lambda value: str(value))
def test_each_class_of_the_registry_exits_with_its_registered_code(name: str, code: int) -> None:
    """The exit code of a class follows its category: 94 rows, none moved by the table."""
    from hydromodpy.core import exceptions

    klass = getattr(exceptions, name)

    assert _load_helpers().exit_code_for(klass.__new__(klass)) == code


def test_every_category_has_its_exit_code() -> None:
    from hydromodpy.core.exceptions import Category

    helpers = _load_helpers()

    assert set(helpers.EXIT_CODE_OF) == set(Category)
    assert len(set(helpers.EXIT_CODE_OF.values())) == len(Category)


def test_a_step_error_exits_with_the_code_of_its_cause() -> None:
    from hydromodpy.core.exceptions import DataError, StepError

    helpers = _load_helpers()
    wrapped = StepError("load_gauge", DataError("no gauge"))

    assert helpers.exit_code_for(wrapped) == helpers.EXIT_VALIDATION


def test_an_exception_outside_the_hierarchy_has_no_category_and_exits_one() -> None:
    helpers = _load_helpers()

    assert helpers.exit_code_for(FileExistsError("taken")) == helpers.EXIT_WRITE_CONFLICT
    assert helpers.exit_code_for(RuntimeError("bug")) == helpers.EXIT_GENERIC


def test_the_exit_codes_of_the_leaves_of_results_come_from_their_category() -> None:
    from hydromodpy.results.catalog.discovery import (
        AmbiguousReferenceError,
        SimulationNotFoundError,
    )
    from hydromodpy.results.storage.attempt import AttemptClaimedError

    helpers = _load_helpers()

    assert (
        helpers.exit_code_for(AmbiguousReferenceError("two", []))
        == helpers.EXIT_AMBIGUOUS_REFERENCE
    )
    assert helpers.exit_code_for(SimulationNotFoundError("none")) == helpers.EXIT_NOT_FOUND
    assert helpers.exit_code_for(AttemptClaimedError("held")) == helpers.EXIT_WRITE_CONFLICT


def test_the_shared_cli_modules_import_nothing_of_results() -> None:
    import ast
    import inspect

    imported = []
    for name in ("exit_codes", "refs", "conventions", "profiling"):
        module = importlib.import_module(f"hydromodpy.cli.{name}")
        tree = ast.parse(inspect.getsource(module))
        imported += [
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and (node.module or "").startswith("hydromodpy.results")
        ]

    assert imported == []
