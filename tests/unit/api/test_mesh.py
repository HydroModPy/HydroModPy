"""Unit tests for ``hmp.mesh``."""

from __future__ import annotations

from pathlib import Path

import pytest

import hydromodpy as hmp

pytestmark = pytest.mark.fast


def _write_toml(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_mesh_routes_through_mesh_catchment_launcher(monkeypatch, tmp_path: Path) -> None:
    """``hmp.mesh`` builds a ``MeshCatchmentLauncher`` and calls ``run``."""
    config = _write_toml(
        tmp_path / "mesh.toml",
        "[mesh_catchment]\nelement_size = 200\n",
    )
    captured: dict = {}

    class FakeLauncher:
        def __init__(self, path):
            captured["init_path"] = path

        def run(self):
            captured["run_called"] = True
            return {"mesh_id": "abc"}

    monkeypatch.setattr("hydromodpy.workflow.pipelines.mesh.MeshCatchmentLauncher", FakeLauncher)

    result = hmp.mesh(config)
    assert result == {"mesh_id": "abc"}
    assert captured["init_path"] == config.resolve()
    assert captured["run_called"] is True


def test_mesh_accepts_string_path(monkeypatch, tmp_path: Path) -> None:
    """A string path is expanded and resolved before launcher init."""
    config = _write_toml(
        tmp_path / "mesh.toml",
        "[mesh_catchment]\nelement_size = 200\n",
    )
    captured: dict = {}

    class FakeLauncher:
        def __init__(self, path):
            captured["init_path"] = path

        def run(self):
            return {}

    monkeypatch.setattr("hydromodpy.workflow.pipelines.mesh.MeshCatchmentLauncher", FakeLauncher)

    hmp.mesh(str(config))
    assert captured["init_path"] == config.resolve()


def test_mesh_propagates_launcher_errors(monkeypatch, tmp_path: Path) -> None:
    """Errors raised inside the launcher reach the caller."""
    config = _write_toml(
        tmp_path / "mesh.toml",
        "[mesh_catchment]\nelement_size = 200\n",
    )

    class FakeLauncher:
        def __init__(self, path):
            raise FileNotFoundError("mesh broken")

        def run(self):
            return {}

    monkeypatch.setattr("hydromodpy.workflow.pipelines.mesh.MeshCatchmentLauncher", FakeLauncher)

    with pytest.raises(FileNotFoundError, match="mesh broken"):
        hmp.mesh(config)
