"""``--until`` on a calibration file points at ``--set workflow.mode=simulation``.

``--from``/``--until`` step to a single-run pipeline, which a calibration file
does not have. The generic refusal only names the mismatch; a soil run is
usually checked alone with ``hmp run <file> --until load_data``, so the
calibration case gets its own text (C1) naming the workaround.
"""

from __future__ import annotations

import importlib
import sys

import pytest


def _run(monkeypatch, argv: list[str]) -> int:
    module = importlib.import_module("hydromodpy.cli.main")
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as exc_info:
        module.main()
    return int(exc_info.value.code or 0)


def test_until_on_a_calibration_file_names_the_simulation_workaround(
    monkeypatch, tmp_path, capsys
) -> None:
    config_path = tmp_path / "calibration.toml"
    config_path.write_text('[workflow]\nmode = "calibration"\n', encoding="utf-8")

    code = _run(monkeypatch, ["hmp", "run", str(config_path), "--until", "load_data"])

    from hydromodpy.cli.helpers import EXIT_CONFIG

    assert code == EXIT_CONFIG
    err = capsys.readouterr().err
    assert (
        "--from / --until are only supported for the 'simulation' workflow "
        "(detected 'calibration'). To run the first steps of this file, for "
        "example to check the soil reservoir alone, add "
        "--set workflow.mode=simulation: "
        "hmp run calibration.toml --until load_data --set workflow.mode=simulation"
    ) in err


def test_from_on_a_calibration_file_gets_the_same_text(monkeypatch, tmp_path, capsys) -> None:
    config_path = tmp_path / "calibration.toml"
    config_path.write_text('[workflow]\nmode = "calibration"\n', encoding="utf-8")

    code = _run(monkeypatch, ["hmp", "run", str(config_path), "--from", "load_data"])

    from hydromodpy.cli.helpers import EXIT_CONFIG

    assert code == EXIT_CONFIG
    err = capsys.readouterr().err
    assert "--set workflow.mode=simulation" in err
    assert "detected 'calibration'" in err


def test_until_on_an_overview_file_keeps_the_generic_text(monkeypatch, tmp_path, capsys) -> None:
    config_path = tmp_path / "overview.toml"
    config_path.write_text('[workflow]\nmode = "overview"\n', encoding="utf-8")

    code = _run(monkeypatch, ["hmp", "run", str(config_path), "--until", "load_data"])

    from hydromodpy.cli.helpers import EXIT_CONFIG

    assert code == EXIT_CONFIG
    err = capsys.readouterr().err
    assert "detected 'overview'" in err
    assert "workflow.mode=simulation" not in err
