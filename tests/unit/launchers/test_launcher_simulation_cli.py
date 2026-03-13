"""Unit tests for launcher_simulation CLI argument handling."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest


def _load_module():
    return importlib.import_module("examples.launcher_simulation.launcher_simulation")


def test_launcher_simulation_uses_default_config_when_no_argument(monkeypatch) -> None:
    module = _load_module()
    captured: dict[str, object] = {}

    class DummyLauncher:
        def __init__(self, config_path: Path) -> None:
            captured["config_path"] = Path(config_path)

        def run(self) -> None:
            captured["run_called"] = True

    monkeypatch.setattr(module, "HydroModPyLauncher", DummyLauncher)

    module.main([])

    expected = (Path(module.__file__).resolve().parent / "config_extensive_nwt.toml").resolve()
    assert captured["config_path"] == expected
    assert captured["run_called"] is True


def test_launcher_simulation_accepts_config_from_cli(monkeypatch) -> None:
    module = _load_module()
    captured: dict[str, object] = {}

    custom_config = Path(module.__file__).resolve().parent / "config_fast_mf6.toml"

    class DummyLauncher:
        def __init__(self, config_path: Path) -> None:
            captured["config_path"] = Path(config_path)

        def run(self) -> None:
            captured["run_called"] = True

    monkeypatch.setattr(module, "HydroModPyLauncher", DummyLauncher)

    module.main([str(custom_config)])

    assert captured["config_path"] == custom_config.resolve()
    assert captured["run_called"] is True


def test_launcher_simulation_reports_legacy_config_rename() -> None:
    module = _load_module()

    legacy_config = Path(module.__file__).resolve().parent / "config_standard.toml"

    with pytest.raises(FileNotFoundError, match="config_extensive_nwt.toml"):
        module.main([str(legacy_config)])
