"""Unit tests for the generic ``python -m launchers`` CLI wrapper."""

from __future__ import annotations

import importlib
from pathlib import Path


def _load_module():
    return importlib.import_module("launchers.__main__")


def test_launchers_cli_simulation_dispatches_to_launcher(monkeypatch, tmp_path) -> None:
    module = _load_module()
    captured: dict[str, Path] = {}

    config_path = tmp_path / "config.toml"
    config_path.write_text("# test\n", encoding="utf-8")

    def _fake_runner(path: Path) -> None:
        captured["config"] = path

    monkeypatch.setattr(module, "_run_simulation_launcher", _fake_runner)

    code = module.main(["simulation", str(config_path)])

    assert code == 0
    assert captured["config"] == config_path.resolve()


def test_launchers_cli_mesh_catchment_run_dispatches_to_launcher(monkeypatch, tmp_path) -> None:
    module = _load_module()
    captured: dict[str, Path] = {}

    config_path = tmp_path / "config.toml"
    config_path.write_text("# test\n", encoding="utf-8")

    def _fake_runner(path: Path) -> None:
        captured["config"] = path

    monkeypatch.setattr(module, "_run_mesh_catchment_launcher", _fake_runner)

    code = module.main(["mesh-catchment", "run", str(config_path)])

    assert code == 0
    assert captured["config"] == config_path.resolve()


def test_launchers_cli_rejects_unknown_command(tmp_path) -> None:
    module = _load_module()

    config_path = tmp_path / "config.toml"
    config_path.write_text("# test\n", encoding="utf-8")

    code = module.main(["unknown_command", str(config_path)])

    assert code != 0


def test_launchers_cli_returns_error_when_missing_config() -> None:
    module = _load_module()

    code = module.main(["simulation"])

    assert code != 0


def test_launchers_cli_mesh_catchment_returns_error_when_missing_config() -> None:
    module = _load_module()

    code = module.main(["mesh-catchment", "run"])

    assert code != 0
