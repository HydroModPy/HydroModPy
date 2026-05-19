"""Unit tests for ``hmp.run``."""

from __future__ import annotations

from pathlib import Path

import pytest

import hydromodpy as hmp

pytestmark = pytest.mark.fast


def _write_toml(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_run_with_path_dispatches_via_workflow(monkeypatch, tmp_path: Path) -> None:
    """A TOML path is routed through ``dispatch_workflow``."""
    config = _write_toml(
        tmp_path / "config.toml",
        '[workflow]\nmode = "simulation"\n[workspace]\nproject_root = "."\n'
        '[simulation]\nname = "test"\n',
    )
    captured: dict = {}

    def fake_resolve(config_path, *, cli_workflow=None, require_toml_field=True):
        captured["config_path"] = Path(config_path)
        captured["cli_workflow"] = cli_workflow
        captured["require_toml_field"] = require_toml_field
        return "simulation"

    def fake_dispatch(workflow, config_path, **kwargs):
        captured["workflow"] = workflow
        captured["dispatch_path"] = Path(config_path)
        captured["kwargs"] = kwargs
        return {"sim_id": "abc"}

    monkeypatch.setattr("hydromodpy.workflow.dispatch.resolve_workflow", fake_resolve)
    monkeypatch.setattr("hydromodpy.project.dispatch.workflow.dispatch_workflow", fake_dispatch)

    result = hmp.run(config, name="baseline")
    assert result == {"sim_id": "abc"}
    assert captured["workflow"] == "simulation"
    assert captured["dispatch_path"] == config.resolve()
    assert captured["kwargs"] == {"name": "baseline"}
    assert captured["cli_workflow"] is None
    assert captured["require_toml_field"] is True


def test_run_with_string_path_resolves(monkeypatch, tmp_path: Path) -> None:
    """A string path is expanded and resolved before dispatch."""
    config = _write_toml(
        tmp_path / "config.toml",
        '[workflow]\nmode = "simulation"\n[workspace]\nproject_root = "."\n'
        '[simulation]\nname = "test"\n',
    )
    captured: dict = {}

    monkeypatch.setattr(
        "hydromodpy.workflow.dispatch.resolve_workflow",
        lambda p, *, cli_workflow=None, require_toml_field=True: "simulation",
    )

    def fake_dispatch(workflow, config_path, **kwargs):
        captured["dispatch_path"] = Path(config_path)
        return {}

    monkeypatch.setattr("hydromodpy.project.dispatch.workflow.dispatch_workflow", fake_dispatch)

    hmp.run(str(config))
    assert captured["dispatch_path"] == config.resolve()


def test_run_with_config_object_uses_project(monkeypatch) -> None:
    """A non-path config object opens a ``Project`` and calls ``project.run``."""
    captured: dict = {}

    class FakeProject:
        def __init__(self, cfg, *, headless=False):
            captured["cfg"] = cfg
            captured["headless"] = headless

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            captured["closed"] = True

        def run(self, **kwargs):
            captured["run_kwargs"] = kwargs
            return {"name": "from_object"}

    monkeypatch.setattr("hydromodpy.project.Project", FakeProject)

    fake_cfg = object()
    result = hmp.run(fake_cfg, name="alpha", headless=True)
    assert result == {"name": "from_object"}
    assert captured["cfg"] is fake_cfg
    assert captured["headless"] is True
    assert captured["run_kwargs"] == {"name": "alpha"}
    assert captured["closed"] is True
