"""Unit tests for ``hmp.calibrate``."""

from __future__ import annotations

from pathlib import Path

import pytest

import hydromodpy as hmp
from tests._helpers.api_doubles import make_capturing_project

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


@pytest.mark.parametrize("headless", [True, False])
def test_calibrate_object_config_routes_to_project(monkeypatch, headless: bool) -> None:
    """A non-path config opens a Project and delegates to ``project.calibrate``.

    ``headless`` reaches the Project constructor, not the verb kwargs; the
    user kwargs (here ``max_iter``) reach ``calibrate`` untouched and never
    leak a ``config_path``.
    """
    captured: dict = {}
    monkeypatch.setattr(
        "hydromodpy.project.Project",
        make_capturing_project(captured, result={"report": "from_object"}, verb="calibrate"),
    )

    fake_cfg = object()
    result = hmp.calibrate(fake_cfg, headless=headless, max_iter=10)
    assert result == {"report": "from_object"}
    assert captured["init_cfg"] is fake_cfg
    assert captured["init_headless"] is headless
    assert captured["verb_kwargs"] == {"max_iter": 10}
    assert "config_path" not in captured["verb_kwargs"]
    assert "headless" not in captured["verb_kwargs"]
    assert captured["closed"] is True
