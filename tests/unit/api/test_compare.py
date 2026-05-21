"""Unit tests for ``hmp.compare``."""

from __future__ import annotations

from pathlib import Path

import pytest

import hydromodpy as hmp

pytestmark = pytest.mark.fast


def _write_toml(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_compare_dispatches_comparison_workflow(monkeypatch, tmp_path: Path) -> None:
    """A TOML with ``mode = 'comparison'`` reaches the comparison dispatcher."""
    config = _write_toml(
        tmp_path / "cmp.toml",
        '[workflow]\nmode = "comparison"\n[comparison]\nbase_simulation_config = "base.toml"\n',
    )
    captured: dict = {}

    def fake_resolve(config_path, *, cli_workflow=None, require_toml_field=True):
        captured["cli_workflow"] = cli_workflow
        captured["require_toml_field"] = require_toml_field
        captured["config_path"] = Path(config_path)
        return "comparison"

    def fake_dispatch(workflow, config_path, **kwargs):
        captured["workflow"] = workflow
        captured["dispatch_path"] = Path(config_path)
        captured["kwargs"] = kwargs
        return {"launcher": "fake_comparison"}

    monkeypatch.setattr("hydromodpy.workflow.dispatch.resolve_workflow", fake_resolve)
    monkeypatch.setattr("hydromodpy.project.dispatch.workflow.dispatch_workflow", fake_dispatch)

    result = hmp.compare(config)
    assert result == {"launcher": "fake_comparison"}
    assert captured["workflow"] == "comparison"
    assert captured["dispatch_path"] == config.resolve()
    assert captured["cli_workflow"] == "comparison"
    assert captured["require_toml_field"] is True
    assert captured["kwargs"] == {}


def test_compare_resolves_string_path(monkeypatch, tmp_path: Path) -> None:
    """``hmp.compare`` resolves a string path."""
    config = _write_toml(
        tmp_path / "cmp.toml",
        '[workflow]\nmode = "comparison"\n[comparison]\nbase_simulation_config = "x"\n',
    )
    captured: dict = {}

    monkeypatch.setattr(
        "hydromodpy.workflow.dispatch.resolve_workflow",
        lambda p, *, cli_workflow=None, require_toml_field=True: "comparison",
    )

    def fake_dispatch(workflow, config_path, **kwargs):
        captured["path"] = Path(config_path)
        return {}

    monkeypatch.setattr("hydromodpy.project.dispatch.workflow.dispatch_workflow", fake_dispatch)

    hmp.compare(str(config))
    assert captured["path"] == config.resolve()
