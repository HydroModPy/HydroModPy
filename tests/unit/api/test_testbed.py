"""Unit tests for ``hmp.testbed``."""

from __future__ import annotations

from pathlib import Path

import pytest

import hydromodpy as hmp

pytestmark = pytest.mark.fast


def _write_toml(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_testbed_routes_through_run_testbed(monkeypatch, tmp_path: Path) -> None:
    """``hmp.testbed`` goes through ``run_testbed``, not direct TestbedLauncher."""
    config = _write_toml(
        tmp_path / "tb.toml",
        '[workflow]\nmode = "testbed"\n[testbed]\nprofile = "generic"\n',
    )
    captured: dict = {}

    def fake_run_testbed(path):
        captured["path"] = path
        return {"launcher": "fake_testbed"}

    monkeypatch.setattr("hydromodpy.project.dispatch.workflow.run_testbed", fake_run_testbed)

    result = hmp.testbed(config)
    assert captured["path"] == config.resolve()
    assert result == {"launcher": "fake_testbed"}


def test_testbed_accepts_string_path(monkeypatch, tmp_path: Path) -> None:
    """A string path is expanded and resolved."""
    config = _write_toml(
        tmp_path / "tb.toml",
        '[workflow]\nmode = "testbed"\n[testbed]\nprofile = "generic"\n',
    )
    captured: dict = {}

    monkeypatch.setattr(
        "hydromodpy.project.dispatch.workflow.run_testbed",
        lambda path: captured.setdefault("path", path) or {},
    )

    hmp.testbed(str(config))
    assert captured["path"] == config.resolve()


def test_testbed_propagates_errors(monkeypatch, tmp_path: Path) -> None:
    """Errors raised by ``run_testbed`` propagate to the caller."""
    config = _write_toml(
        tmp_path / "tb.toml",
        '[workflow]\nmode = "testbed"\n[testbed]\nprofile = "bad"\n',
    )

    def fake_run_testbed(path):
        raise ValueError("bad profile")

    monkeypatch.setattr("hydromodpy.project.dispatch.workflow.run_testbed", fake_run_testbed)

    with pytest.raises(ValueError, match="bad profile"):
        hmp.testbed(config)
