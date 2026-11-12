"""``catalog_path`` and ``runs_dir`` are read-only: the storage layout contract fixes them."""

from __future__ import annotations

from pathlib import Path

from hydromodpy.core.workspace.config import WorkspaceConfig


def test_the_index_and_the_runs_follow_the_project_root(tmp_path: Path) -> None:
    config = WorkspaceConfig(project_root=tmp_path)
    assert config.catalog_path == tmp_path.resolve() / ".hmp" / "index.duckdb"
    assert config.runs_dir == tmp_path.resolve() / "runs"
