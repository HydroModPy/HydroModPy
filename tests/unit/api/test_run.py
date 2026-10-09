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


def _fake_cfg(root: Path, name: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        workflow=SimpleNamespace(mode="simulation"),
        workspace=SimpleNamespace(project_root=root),
        simulation=SimpleNamespace(name=name),
    )


def test_run_with_config_object_uses_project(monkeypatch, tmp_path: Path) -> None:
    """A non-path config object opens a ``Project`` and calls ``project.simulate``."""
    captured: dict = {}
    verb_result = SimpleNamespace(name="from_object", sim_id="sim-001")
    monkeypatch.setattr(
        "hydromodpy.project.Project",
        make_capturing_project(captured, result=verb_result, verb="simulate"),
    )
    rebound = object()
    opened: dict = {}

    def fake_open_run(root, sim_id):
        opened["args"] = (root, sim_id)
        return rebound

    monkeypatch.setattr("hydromodpy._api._open_run", fake_open_run)

    fake_cfg = _fake_cfg(tmp_path)
    result = hmp.run(fake_cfg, name="alpha", headless=True, no_lock=True)
    assert result is rebound
    assert opened["args"] == (tmp_path, "sim-001")
    assert captured["init_cfg"] is fake_cfg
    assert captured["init_headless"] is True
    assert captured["verb_kwargs"] == {"name": "alpha"}
    assert captured["closed"] is True


def test_a_finished_run_without_a_readable_catalog_raises(monkeypatch, tmp_path: Path) -> None:
    """``None`` means a dry run; a finished run whose catalog fails says so."""
    from hydromodpy.core.exceptions import CatalogError

    captured: dict = {}
    monkeypatch.setattr(
        "hydromodpy.project.Project",
        make_capturing_project(
            captured, result=SimpleNamespace(name="x", sim_id="sim-001"), verb="simulate"
        ),
    )
    with pytest.raises(CatalogError, match="finished, but the catalog"):
        hmp.run(_fake_cfg(tmp_path / "nowhere"), name="x", no_lock=True)


def test_force_is_not_a_parameter_override(monkeypatch, tmp_path: Path) -> None:
    captured: dict = {}
    monkeypatch.setattr(
        "hydromodpy.project.Project",
        make_capturing_project(
            captured, result=SimpleNamespace(name="x", sim_id="s"), verb="simulate"
        ),
    )
    monkeypatch.setattr("hydromodpy._api._open_run", lambda root, sid: sid)
    hmp.run(_fake_cfg(tmp_path, name="x"), force=True, no_lock=True)
    assert captured["verb_kwargs"] == {}


def test_an_identical_completed_run_is_returned_not_recomputed(monkeypatch, tmp_path: Path) -> None:
    """``hmp.run(cfg)`` skips like ``hmp run``; ``force=True`` computes anyway."""
    captured: dict = {}
    monkeypatch.setattr(
        "hydromodpy.project.Project",
        make_capturing_project(
            captured, result=SimpleNamespace(name="x.v2", sim_id="new"), verb="simulate"
        ),
    )
    asked: dict = {}

    def fake_identical(config, *, name):
        asked["name"] = name
        return ("x", "old-sim")

    monkeypatch.setattr(
        "hydromodpy.project.dispatch.workflow.completed_identical_run", fake_identical
    )
    monkeypatch.setattr("hydromodpy._api._open_run", lambda root, sid: sid)

    assert hmp.run(_fake_cfg(tmp_path, name="x"), no_lock=True) == "old-sim"
    assert asked["name"] == "x"
    assert "verb_kwargs" not in captured

    assert hmp.run(_fake_cfg(tmp_path, name="x"), force=True, no_lock=True) == "new"
    # A parameter override is another run: never skipped.
    captured.clear()
    assert hmp.run(_fake_cfg(tmp_path, name="x"), K=1e-5, no_lock=True) == "new"
    assert captured["verb_kwargs"] == {"K": 1e-5}


def test_a_path_takes_a_name_and_refuses_an_override(monkeypatch, tmp_path: Path) -> None:
    config = _write_toml(tmp_path / "sim.toml", '[workflow]\nmode = "simulation"\n')
    monkeypatch.setattr(
        "hydromodpy.workflow.dispatch.resolve_workflow",
        lambda p, *, cli_workflow=None, require_toml_field=True: "simulation",
    )
    captured: dict = {}

    def fake_dispatch(workflow, config_path, **kwargs):
        captured["kwargs"] = kwargs
        return {"name": "x", "sim_id": "sid", "project_root": str(tmp_path)}

    monkeypatch.setattr("hydromodpy.project.dispatch.workflow.dispatch_workflow", fake_dispatch)
    monkeypatch.setattr("hydromodpy._api._open_run", lambda root, sid: (root, sid))

    assert hmp.run(config, name="x", no_lock=True) == (str(tmp_path), "sid")
    assert captured["kwargs"] == {"name": "x"}

    with pytest.raises(TypeError, match="takes no parameter override"):
        hmp.run(config, K=1e-5)
