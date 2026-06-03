"""Unit tests for ``hmp.calibrate``."""

from __future__ import annotations

from pathlib import Path

import pytest

import hydromodpy as hmp

pytestmark = pytest.mark.fast


def _write_toml(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_calibrate_with_path_routes_to_run_calibration_cli(monkeypatch, tmp_path: Path) -> None:
    """A TOML path calls ``run_calibration_cli`` directly (no Project detour)."""
    config = _write_toml(
        tmp_path / "calib.toml",
        '[workflow]\nmode = "calibration"\n[calibration]\nmethod = "scipy"\n',
    )
    captured: dict = {}

    def fake_cli(config_path, **kwargs):
        captured["config_path"] = Path(config_path)
        captured["kwargs"] = kwargs
        return {"report": "ok"}

    monkeypatch.setattr("hydromodpy.calibration.cli_runner.run_calibration_cli", fake_cli)

    result = hmp.calibrate(config, project="my_label")
    assert result == {"report": "ok"}
    assert captured["config_path"] == config.resolve()
    assert captured["kwargs"] == {"project": "my_label"}


def test_calibrate_with_path_drops_headless_kwarg(monkeypatch, tmp_path: Path) -> None:
    """``headless`` does not reach the CLI runner on the TOML branch."""
    config = _write_toml(
        tmp_path / "calib.toml",
        '[workflow]\nmode = "calibration"\n',
    )
    captured: dict = {}

    def fake_cli(config_path, **kwargs):
        captured["kwargs"] = kwargs
        return None

    monkeypatch.setattr("hydromodpy.calibration.cli_runner.run_calibration_cli", fake_cli)

    hmp.calibrate(config, headless=False)
    assert "headless" not in captured["kwargs"]


def test_calibrate_with_object_config(monkeypatch) -> None:
    """A non-path config opens a lazy Project and delegates to ``project.calibrate``."""
    captured: dict = {}

    class FakeProject:
        def __init__(self, cfg, *, headless=True):
            captured["init_cfg"] = cfg
            captured["init_headless"] = headless

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            captured["closed"] = True

        def calibrate(self, **kwargs):
            captured["calibrate_kwargs"] = kwargs
            return {"report": "from_object"}

    monkeypatch.setattr("hydromodpy.project.Project", FakeProject)

    fake_cfg = object()
    result = hmp.calibrate(fake_cfg, max_iter=10)
    assert result == {"report": "from_object"}
    assert captured["init_cfg"] is fake_cfg
    assert captured["init_headless"] is True
    assert "config_path" not in captured["calibrate_kwargs"]
    assert captured["calibrate_kwargs"] == {"max_iter": 10}


def test_calibrate_object_config_honors_headless_override(monkeypatch) -> None:
    """``headless`` is forwarded to the Project constructor on the object branch."""
    captured: dict = {}

    class FakeProject:
        def __init__(self, cfg, *, headless=True):
            captured["headless"] = headless

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            pass

        def calibrate(self, **kwargs):
            captured["kwargs"] = kwargs
            return None

    monkeypatch.setattr("hydromodpy.project.Project", FakeProject)

    fake_cfg = object()
    hmp.calibrate(fake_cfg, headless=False)
    assert captured["headless"] is False
    assert "headless" not in captured["kwargs"]
