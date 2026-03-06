"""Unit tests for launcher_simulation CLI argument handling."""

from __future__ import annotations

import importlib
from pathlib import Path


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

    expected = (Path(module.__file__).resolve().parent / "config_standard.toml").resolve()
    assert captured["config_path"] == expected
    assert captured["run_called"] is True


def test_launcher_simulation_accepts_config_from_cli(monkeypatch, tmp_path) -> None:
    module = _load_module()
    captured: dict[str, object] = {}

    custom_config = tmp_path / "custom.toml"
    custom_config.write_text("# test config\n", encoding="utf-8")

    class DummyLauncher:
        def __init__(self, config_path: Path) -> None:
            captured["config_path"] = Path(config_path)

        def run(self) -> None:
            captured["run_called"] = True

    monkeypatch.setattr(module, "HydroModPyLauncher", DummyLauncher)

    module.main([str(custom_config)])

    assert captured["config_path"] == custom_config.resolve()
    assert captured["run_called"] is True
