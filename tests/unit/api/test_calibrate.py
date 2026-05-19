"""Unit tests for ``hmp.calibrate``."""

from __future__ import annotations

from pathlib import Path

import pytest

import hydromodpy as hmp

pytestmark = pytest.mark.fast


def _write_toml(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_calibrate_with_path_routes_via_project_lazy(monkeypatch, tmp_path: Path) -> None:
    """A TOML path opens a lazy Project and forwards to ``project.calibrate``."""
    config = _write_toml(
        tmp_path / "calib.toml",
        '[workflow]\nmode = "calibration"\n[calibration]\nmethod = "scipy"\n',
    )
    captured: dict = {}

    class FakeProject:
        @classmethod
        def lazy(cls, cfg, *, headless=True):
            captured["lazy_cfg"] = cfg
            captured["lazy_headless"] = headless
            return cls()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            captured["closed"] = True

        def calibrate(self, **kwargs):
            captured["calibrate_kwargs"] = kwargs
            return {"report": "ok"}

    monkeypatch.setattr("hydromodpy.project.Project", FakeProject)

    result = hmp.calibrate(config, seed=42)
    assert result == {"report": "ok"}
    assert captured["lazy_cfg"] == config.resolve()
    assert captured["lazy_headless"] is True
    assert captured["calibrate_kwargs"]["config_path"] == config.resolve()
    assert captured["calibrate_kwargs"]["seed"] == 42
    assert captured["closed"] is True


def test_calibrate_with_object_config(monkeypatch) -> None:
    """A non-path config opens a lazy Project without forwarding ``config_path``."""
    captured: dict = {}

    class FakeProject:
        @classmethod
        def lazy(cls, cfg, *, headless=True):
            captured["lazy_cfg"] = cfg
            captured["lazy_headless"] = headless
            return cls()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            pass

        def calibrate(self, **kwargs):
            captured["calibrate_kwargs"] = kwargs
            return {"report": "from_object"}

    monkeypatch.setattr("hydromodpy.project.Project", FakeProject)

    fake_cfg = object()
    result = hmp.calibrate(fake_cfg, max_iter=10)
    assert result == {"report": "from_object"}
    assert captured["lazy_cfg"] is fake_cfg
    assert captured["lazy_headless"] is True
    assert "config_path" not in captured["calibrate_kwargs"]
    assert captured["calibrate_kwargs"] == {"max_iter": 10}


def test_calibrate_forwards_headless_override(monkeypatch, tmp_path: Path) -> None:
    """``headless`` is consumed by the facade and forwarded to ``Project.lazy``."""
    config = _write_toml(
        tmp_path / "calib.toml",
        '[workflow]\nmode = "calibration"\n[calibration]\nmethod = "scipy"\n',
    )
    captured: dict = {}

    class FakeProject:
        @classmethod
        def lazy(cls, cfg, *, headless=True):
            captured["headless"] = headless
            return cls()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            pass

        def calibrate(self, **kwargs):
            captured["kwargs"] = kwargs
            return None

    monkeypatch.setattr("hydromodpy.project.Project", FakeProject)
    hmp.calibrate(config, headless=False)
    assert captured["headless"] is False
    assert "headless" not in captured["kwargs"]
