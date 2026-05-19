"""Unit tests for ``hmp.overview``."""

from __future__ import annotations

from pathlib import Path

import pytest

import hydromodpy as hmp

pytestmark = pytest.mark.fast


def _write_toml(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_overview_dispatches_overview_workflow(monkeypatch, tmp_path: Path) -> None:
    """A TOML with ``mode = 'overview'`` reaches the overview dispatcher."""
    config = _write_toml(
        tmp_path / "ov.toml",
        '[workflow]\nmode = "overview"\n[workspace]\nproject_root = "."\n'
        '[overview]\nname = "test"\n',
    )
    captured: dict = {}

    def fake_resolve(config_path, *, cli_workflow=None, require_toml_field=True):
        captured["config_path"] = Path(config_path)
        captured["cli_workflow"] = cli_workflow
        captured["require_toml_field"] = require_toml_field
        return "overview"

    def fake_dispatch(workflow, config_path, **kwargs):
        captured["workflow"] = workflow
        captured["dispatch_path"] = Path(config_path)
        captured["kwargs"] = kwargs
        return {"mode": "overview"}

    monkeypatch.setattr("hydromodpy.workflow.dispatch.resolve_workflow", fake_resolve)
    monkeypatch.setattr("hydromodpy.project.dispatch.workflow.dispatch_workflow", fake_dispatch)

    result = hmp.overview(config)
    assert result == {"mode": "overview"}
    assert captured["workflow"] == "overview"
    assert captured["dispatch_path"] == config.resolve()
    assert captured["cli_workflow"] == "overview"
    assert captured["require_toml_field"] is True


def test_overview_resolves_string_path(monkeypatch, tmp_path: Path) -> None:
    """A string path is expanded and resolved before dispatch."""
    config = _write_toml(
        tmp_path / "ov.toml",
        '[workflow]\nmode = "overview"\n[overview]\nname = "ws"\n',
    )
    captured: dict = {}

    monkeypatch.setattr(
        "hydromodpy.workflow.dispatch.resolve_workflow",
        lambda p, *, cli_workflow=None, require_toml_field=True: "overview",
    )

    def fake_dispatch(workflow, config_path, **kwargs):
        captured["path"] = Path(config_path)
        return {}

    monkeypatch.setattr("hydromodpy.project.dispatch.workflow.dispatch_workflow", fake_dispatch)

    hmp.overview(str(config))
    assert captured["path"] == config.resolve()


def test_overview_forwards_kwargs(monkeypatch, tmp_path: Path) -> None:
    """Additional kwargs flow through to the dispatcher."""
    config = _write_toml(
        tmp_path / "ov.toml",
        '[workflow]\nmode = "overview"\n[overview]\nname = "ws"\n',
    )
    captured: dict = {}

    monkeypatch.setattr(
        "hydromodpy.workflow.dispatch.resolve_workflow",
        lambda p, *, cli_workflow=None, require_toml_field=True: "overview",
    )

    def fake_dispatch(workflow, config_path, **kwargs):
        captured["kwargs"] = kwargs
        return {}

    monkeypatch.setattr("hydromodpy.project.dispatch.workflow.dispatch_workflow", fake_dispatch)

    hmp.overview(config, label="alpha")
    assert captured["kwargs"] == {"label": "alpha"}
