"""Folder layout of a workspace: where the solver binaries are looked up."""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.core.state.portable import cache_dir
from hydromodpy.core.workspace.config import WorkspaceConfig
from hydromodpy.core.workspace.workspace import WorkspaceLayout


def test_bin_path_defaults_to_managed_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("HMP_BIN", raising=False)
    project = tmp_path / "ws" / "projects" / "demo"
    project.mkdir(parents=True)
    (tmp_path / "ws" / "data").mkdir()

    workspace = WorkspaceLayout(config=WorkspaceConfig(project_root=project))

    assert Path(workspace.bin_path).resolve() == (cache_dir() / "bin").resolve()
