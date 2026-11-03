import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from hydromodpy.core.state.paths import (
    CATALOG_FILENAME,
    INTERNAL_DIRNAME,
    RUNS_DIRNAME,
)
from hydromodpy.core.workspace import (
    WorkspaceConfig,
    WorkspaceLayout,
    WorkspacePathRegistry,
)


def _scaffold(workspace_dir: Path, project: str = "demo") -> Path:
    """Create a minimal scaffolded workspace and return the project path."""
    workspace_dir.mkdir(parents=True, exist_ok=True)
    (workspace_dir / "data").mkdir(exist_ok=True)
    project_dir = workspace_dir / "projects" / project
    project_dir.mkdir(parents=True, exist_ok=True)
    return project_dir


def test_workspace_bin_path_defaults_to_managed_cache(tmp_path, monkeypatch) -> None:
    """Without HMP_BIN, bin_path resolves to the managed cache."""
    monkeypatch.delenv("HMP_BIN", raising=False)

    from hydromodpy.core.state.paths import cache_dir

    project = _scaffold(tmp_path / "ws")
    cfg = WorkspaceConfig(project_root=project)
    workspace = WorkspaceLayout(config=cfg)

    assert Path(workspace.bin_path).resolve() == (cache_dir() / "bin").resolve()


def test_workspace_bin_path_honours_env_override(tmp_path, monkeypatch) -> None:
    """HMP_BIN overrides the cache when set."""
    custom_bin = tmp_path / "custom_bin"
    custom_bin.mkdir()
    monkeypatch.setenv("HMP_BIN", str(custom_bin))

    project = _scaffold(tmp_path / "ws")
    cfg = WorkspaceConfig(project_root=project)
    workspace = WorkspaceLayout(config=cfg)

    assert Path(workspace.bin_path).resolve() == custom_bin.resolve()


def test_workspace_exposes_canonical_path_registry(tmp_path) -> None:
    project = _scaffold(tmp_path / "ws")
    cfg = WorkspaceConfig(project_root=project)
    workspace = WorkspaceLayout(config=cfg)

    assert isinstance(workspace.paths, WorkspacePathRegistry)
    assert workspace.paths.project_root == workspace.project_root


def test_workspace_creates_folder_structure(tmp_path) -> None:
    project = _scaffold(tmp_path / "ws")
    cfg = WorkspaceConfig(project_root=project)
    workspace = WorkspaceLayout(config=cfg)

    assert workspace.project_root.is_dir()
    assert workspace.solver_scratch_folder == (
        workspace.project_root / INTERNAL_DIRNAME / "scratch"
    )


def test_workspace_resolves_scaffold(tmp_path) -> None:
    """Scaffold layout: <ws>/projects/<name>/hydromodpy.toml derives root."""
    ws_root = tmp_path / "myworkspace"
    project = _scaffold(ws_root)
    cfg = WorkspaceConfig(project_root=project)
    assert cfg.root == ws_root.resolve()
    assert cfg.resolution_source == "scaffold"


def test_workspace_resolves_explicit_root(tmp_path) -> None:
    """Explicit [workspace] root wins regardless of scaffold layout."""
    ws_root = tmp_path / "elsewhere"
    ws_root.mkdir()
    project = tmp_path / "some" / "other" / "place"
    project.mkdir(parents=True)
    cfg = WorkspaceConfig(project_root=project, root=ws_root)
    assert cfg.root == ws_root.resolve()
    assert cfg.resolution_source == "explicit"


def test_workspace_resolves_env_var(tmp_path, monkeypatch) -> None:
    ws_root = tmp_path / "envworkspace"
    ws_root.mkdir()
    monkeypatch.setenv("HMP_WORKSPACE", str(ws_root))
    project = tmp_path / "standalone_project"
    project.mkdir()
    cfg = WorkspaceConfig(project_root=project)
    assert cfg.root == ws_root.resolve()
    assert cfg.resolution_source == "env"


def test_workspace_standalone_project_falls_back_to_project_root(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("HMP_WORKSPACE", raising=False)
    project = tmp_path / "standalone_project"
    project.mkdir()
    cfg = WorkspaceConfig(project_root=project)
    assert cfg.root == project.resolve()
    assert cfg.catalog_path == (project / INTERNAL_DIRNAME / CATALOG_FILENAME).resolve()
    assert cfg.resolution_source == "project"


def test_workspace_data_path_from_workspace_root(tmp_path) -> None:
    ws_root = tmp_path / "myworkspace"
    project = _scaffold(ws_root)
    cfg = WorkspaceConfig(project_root=project)
    assert cfg.data_path == (ws_root / "data").resolve()
    assert cfg.catalog_path == (project / INTERNAL_DIRNAME / CATALOG_FILENAME).resolve()
    assert cfg.runs_dir == (project / RUNS_DIRNAME).resolve()


@pytest.mark.parametrize(
    ("key", "replacement"),
    [
        ("solver_scratch_folder", "HMP_SCRATCH_ROOT"),
        ("share_folder", "runs/<run>/"),
        ("catch_name", "[site] name"),
    ],
)
def test_a_retired_workspace_key_is_refused_with_its_replacement(
    tmp_path, key: str, replacement: str
) -> None:
    project = _scaffold(tmp_path / "ws")
    with pytest.raises(ValidationError, match=re.escape(replacement)):
        WorkspaceConfig(project_root=project, **{key: "x"})


def test_workspace_refuses_a_catalog_path(tmp_path) -> None:
    """The catalog sits in the storage layout; a file cannot place it elsewhere."""
    with pytest.raises(ValidationError, match="catalog_path"):
        WorkspaceConfig(project_root=tmp_path, catalog_path=tmp_path / "custom.duckdb")
