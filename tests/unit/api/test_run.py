"""Unit tests for ``hmp.run``."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import hydromodpy as hmp
from tests._helpers.api_doubles import make_capturing_project

pytestmark = pytest.mark.fast


def _write_toml(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_run_with_overview_toml_dispatches(monkeypatch, tmp_path: Path) -> None:
    """A non-simulation TOML is routed through ``dispatch_workflow``."""
    config = _write_toml(
        tmp_path / "ov.toml",
        '[workflow]\nmode = "overview"\n',
    )
    captured: dict = {}

    def fake_resolve(config_path, *, cli_workflow=None, require_toml_field=True):
        captured["resolve_path"] = Path(config_path)
        return "overview"

    def fake_dispatch(workflow, config_path, **kwargs):
        captured["workflow"] = workflow
        captured["dispatch_path"] = Path(config_path)
        captured["kwargs"] = kwargs
        return {"summary": "ok"}

    monkeypatch.setattr("hydromodpy.workflow.dispatch.resolve_workflow", fake_resolve)
    monkeypatch.setattr("hydromodpy.project.dispatch.workflow.dispatch_workflow", fake_dispatch)

    result = hmp.run(config)
    assert result == {"summary": "ok"}
    assert captured["workflow"] == "overview"
    assert captured["dispatch_path"] == config.resolve()
    assert captured["kwargs"] == {}


def test_run_with_string_path_resolves(monkeypatch, tmp_path: Path) -> None:
    """A string path is expanded and resolved before routing."""
    config = _write_toml(
        tmp_path / "ov.toml",
        '[workflow]\nmode = "overview"\n',
    )
    captured: dict = {}

    monkeypatch.setattr(
        "hydromodpy.workflow.dispatch.resolve_workflow",
        lambda p, *, cli_workflow=None, require_toml_field=True: "overview",
    )

    def fake_dispatch(workflow, config_path, **kwargs):
        captured["dispatch_path"] = Path(config_path)
        return {}

    monkeypatch.setattr("hydromodpy.project.dispatch.workflow.dispatch_workflow", fake_dispatch)

    hmp.run(str(config))
    assert captured["dispatch_path"] == config.resolve()


def test_run_with_config_object_uses_project(monkeypatch, tmp_path: Path) -> None:
    """A non-path config object opens a ``Project`` and calls ``project.simulate``."""
    captured: dict = {}
    # The verb result is re-bound through the catalog of the project root; an
    # empty root has no index, so ``run`` falls back to the verb result itself.
    verb_result = SimpleNamespace(name="from_object", sim_id="sim-001")
    monkeypatch.setattr(
        "hydromodpy.project.Project",
        make_capturing_project(captured, result=verb_result, verb="simulate"),
    )

    fake_cfg = SimpleNamespace(
        workflow=SimpleNamespace(mode="simulation"),
        workspace=SimpleNamespace(project_root=tmp_path),
    )
    result = hmp.run(fake_cfg, name="alpha", headless=True, no_lock=True)
    assert result is verb_result
    assert captured["init_cfg"] is fake_cfg
    assert captured["init_headless"] is True
    assert captured["verb_kwargs"] == {"name": "alpha"}
    assert captured["closed"] is True
