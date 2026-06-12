"""Tests for the P10 extensions to ``hmp doctor`` (--cross-catalog, --lifecycle)."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


def _load_main():
    return importlib.import_module("hydromodpy.cli.main")


def _run(monkeypatch, argv: list[str]) -> int:
    """Run ``hmp`` and tolerate handlers that do not call sys.exit explicitly."""
    module = _load_main()
    monkeypatch.setattr(sys, "argv", argv)
    try:
        module.main()
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


@pytest.fixture
def isolated_state(monkeypatch, tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv("HMP_STATE_HOME", str(state))
    yield state


def _make_workspace_with_catalog(tmp_path: Path) -> Path:
    from hydromodpy.results.catalog import Catalog

    workspace = tmp_path / "ws"
    workspace.mkdir()
    project = workspace / "projects" / "demo"
    project.mkdir(parents=True)
    (project / "simulations").mkdir()
    (workspace / "data").mkdir()
    with Catalog(project):
        pass
    return workspace


def test_doctor_help_lists_new_flags(monkeypatch, capsys) -> None:
    code = _run(monkeypatch, ["hmp", "doctor", "--help"])
    assert code == 0
    out = capsys.readouterr().out
    assert "--cross-catalog" in out
    assert "--lifecycle" in out


def test_doctor_lifecycle_on_clean_workspace(monkeypatch, tmp_path, capsys, isolated_state) -> None:
    workspace = _make_workspace_with_catalog(tmp_path)
    code = _run(
        monkeypatch,
        ["hmp", "doctor", "--workspace", str(workspace), "--lifecycle", "--json"],
    )
    # exit may be 0 even with WARN entries; just verify the new checks render
    assert code in (0, 1)
    out = capsys.readouterr().out
    assert "lifecycle:stale_running_sims" in out
    assert "lifecycle:orphan_calibration_sessions" in out
    assert "lifecycle:tmp_parquet" in out


def test_doctor_cross_catalog_on_workspace(monkeypatch, tmp_path, capsys, isolated_state) -> None:
    workspace = _make_workspace_with_catalog(tmp_path)
    code = _run(
        monkeypatch,
        ["hmp", "doctor", "--workspace", str(workspace), "--cross-catalog", "--json"],
    )
    assert code in (0, 1)
    out = capsys.readouterr().out
    assert "cross_catalog:" in out
