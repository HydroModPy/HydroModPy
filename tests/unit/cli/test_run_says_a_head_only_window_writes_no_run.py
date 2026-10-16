"""``hmp run --until build_mesh`` says why no run directory appears."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

from hydromodpy.cli.commands.run import HEAD_ONLY_MESSAGE, _stops_before_setup_process


def _run(monkeypatch, argv: list[str]) -> int:
    module = importlib.import_module("hydromodpy.cli.main")
    monkeypatch.setattr(sys, "argv", argv)
    try:
        module.main()
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


@pytest.mark.parametrize(
    ("until", "expected"),
    [
        (None, False),
        ("build_geographic", True),
        ("load_data", True),
        ("build_mesh", True),
        ("0", True),
        ("setup_process", False),
        ("run_solver", False),
        ("seal", False),
    ],
)
def test_only_a_window_that_ends_before_setup_process_is_head_only(
    until: str | None, expected: bool
) -> None:
    assert _stops_before_setup_process(until) is expected


def test_a_head_only_window_prints_one_line_and_exits_zero(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    config = tmp_path / "run.toml"
    config.write_text('[workflow]\nmode = "simulation"\n', encoding="utf-8")
    monkeypatch.setattr(
        "hydromodpy.project.dispatch.workflow.dispatch_workflow", lambda *a, **k: {}
    )

    code = _run(monkeypatch, ["hmp", "run", str(config), "--until", "build_mesh", "--case", "x"])

    assert code == 0
    assert HEAD_ONLY_MESSAGE in capsys.readouterr().err
    assert not (tmp_path / "runs").exists()


def test_a_window_that_reaches_the_model_phase_says_nothing_of_it(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    config = tmp_path / "run.toml"
    config.write_text('[workflow]\nmode = "simulation"\n', encoding="utf-8")
    monkeypatch.setattr(
        "hydromodpy.project.dispatch.workflow.dispatch_workflow", lambda *a, **k: {}
    )

    code = _run(monkeypatch, ["hmp", "run", str(config), "--until", "run_solver"])

    assert code == 0
    assert HEAD_ONLY_MESSAGE not in capsys.readouterr().err
