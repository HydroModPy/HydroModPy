"""Unit tests for ``hmp simulation`` CLI subcommand."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.__main__ import main


def _make_dummy_launcher(captured: dict):
    """Return a fake HydroModPyLauncher class that records calls."""

    class DummyLauncher:
        def __init__(self, config_path):
            captured["config_path"] = Path(config_path)

        def run(self):
            captured["run_called"] = True
            return SimpleNamespace(
                execution=SimpleNamespace(models_by_run_id={}),
            )

    return DummyLauncher


def _make_dummy_method_comparison_launcher(captured: dict):
    """Return a fake MethodComparisonLauncher class that records calls."""

    class DummyLauncher:
        def __init__(self, config_path):
            captured["config_path"] = Path(config_path)

        def run(self):
            captured["run_called"] = True
            return {
                "comparison_id": "demo_compare",
                "manifest_path": "comparison_manifest.json",
                "observables_csv": "observables.csv",
            }

    return DummyLauncher


def test_hmp_simulation_dispatches_to_launcher(monkeypatch, tmp_path) -> None:
    config = tmp_path / "config.toml"
    config.write_text("# test config\n", encoding="utf-8")

    captured: dict = {}
    monkeypatch.setattr(
        "launchers.HydroModPyLauncher",
        _make_dummy_launcher(captured),
    )
    monkeypatch.setattr("sys.argv", ["hmp", "simulation", str(config)])

    main()

    assert captured["config_path"] == config.resolve()
    assert captured["run_called"] is True


def test_hmp_simulation_exits_on_missing_file(monkeypatch, tmp_path) -> None:
    missing = tmp_path / "does_not_exist.toml"
    monkeypatch.setattr("sys.argv", ["hmp", "simulation", str(missing)])

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1


def test_hmp_run_dispatches_to_launcher(monkeypatch, tmp_path) -> None:
    """The ``hmp run`` subcommand dispatches to the launcher."""
    config = tmp_path / "config.toml"
    config.write_text("# test config\n", encoding="utf-8")

    captured: dict = {}
    monkeypatch.setattr(
        "launchers.HydroModPyLauncher",
        _make_dummy_launcher(captured),
    )
    monkeypatch.setattr("sys.argv", ["hmp", "run", str(config)])

    main()

    assert captured["config_path"] == config.resolve()
    assert captured["run_called"] is True


def test_hmp_compare_dispatches_to_method_comparison_launcher(
    monkeypatch,
    tmp_path,
) -> None:
    config = tmp_path / "config_method_comparison.toml"
    config.write_text("# test config\n", encoding="utf-8")

    captured: dict = {}
    monkeypatch.setattr(
        "launchers.MethodComparisonLauncher",
        _make_dummy_method_comparison_launcher(captured),
    )
    monkeypatch.setattr("sys.argv", ["hmp", "compare", str(config)])

    main()

    assert captured["config_path"] == config.resolve()
    assert captured["run_called"] is True
