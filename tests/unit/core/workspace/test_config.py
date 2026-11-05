"""``catalog_path`` and ``runs_dir`` are read-only: the storage layout contract fixes them."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from hydromodpy.core.workspace.config import WorkspaceConfig


@pytest.mark.parametrize("key", ["catalog_path", "runs_dir"])
def test_a_file_that_moves_the_index_or_the_runs_is_refused(tmp_path: Path, key: str) -> None:
    with pytest.raises(ValidationError, match="storage layout contract"):
        WorkspaceConfig.model_validate({"project_root": tmp_path, key: str(tmp_path / "x")})


def test_the_index_and_the_runs_follow_the_project_root(tmp_path: Path) -> None:
    config = WorkspaceConfig(project_root=tmp_path)
    assert config.catalog_path == tmp_path.resolve() / ".hmp" / "index.duckdb"
    assert config.runs_dir == tmp_path.resolve() / "runs"
