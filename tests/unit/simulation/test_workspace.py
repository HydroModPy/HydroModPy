from pathlib import Path

import pytest

from hydromodpy.core.workspace import (
    Workspace,
    WorkspaceConfig,
    WorkspaceError,
    WorkspacePathRegistry,
)


def _scaffold(workspace_dir: Path, project: str = "demo") -> Path:
    """Create a minimal scaffolded workspace and return the project path."""
    workspace_dir.mkdir(parents=True, exist_ok=True)
    (workspace_dir / "data").mkdir(exist_ok=True)
    (workspace_dir / "hydromodpy.duckdb").touch()
    project_dir = workspace_dir / "projects" / project
    project_dir.mkdir(parents=True, exist_ok=True)
    return project_dir


def test_workspace_bin_path_resolves_repo_bin(tmp_path) -> None:
    project = _scaffold(tmp_path / "ws")
    cfg = WorkspaceConfig(project_root=project)
    workspace = Workspace(config=cfg)

    expected = (Path(__file__).resolve().parents[3] / "bin").resolve()
    assert Path(workspace.bin_path).resolve() == expected


def test_workspace_exposes_canonical_path_registry(tmp_path) -> None:
    project = _scaffold(tmp_path / "ws")
    cfg = WorkspaceConfig(project_root=project)
    workspace = Workspace(config=cfg)

    assert isinstance(workspace.paths, WorkspacePathRegistry)
    assert workspace.paths.project_root == workspace.project_root
    assert workspace.paths.figures_folder == workspace.figure_folder


def test_workspace_creates_folder_structure(tmp_path) -> None:
    project = _scaffold(tmp_path / "ws")
    cfg = WorkspaceConfig(project_root=project)
    workspace = Workspace(config=cfg)

    assert workspace.project_root.is_dir()
    assert workspace.solver_scratch_folder == workspace.project_root / ".solver_scratch"


def test_workspace_resolves_scaffold(tmp_path) -> None:
    """Scaffold layout: <ws>/projects/<name>/project.toml derives root."""
    ws_root = tmp_path / "myworkspace"
    project = _scaffold(ws_root)
    cfg = WorkspaceConfig(project_root=project)
    assert cfg.workspace_root == ws_root.resolve()
    assert cfg.resolution_source == "scaffold"


def test_workspace_resolves_explicit_root(tmp_path) -> None:
    """Explicit [workspace] root wins regardless of scaffold layout."""
    ws_root = tmp_path / "elsewhere"
    ws_root.mkdir()
    project = tmp_path / "some" / "other" / "place"
    project.mkdir(parents=True)
    cfg = WorkspaceConfig(project_root=project, root=ws_root)
    assert cfg.workspace_root == ws_root.resolve()
    assert cfg.resolution_source == "explicit"


def test_workspace_resolves_env_var(tmp_path, monkeypatch) -> None:
    ws_root = tmp_path / "envworkspace"
    ws_root.mkdir()
    monkeypatch.setenv("HYDROMODPY_WORKSPACE", str(ws_root))
    project = tmp_path / "standalone_project"
    project.mkdir()
    cfg = WorkspaceConfig(project_root=project)
    assert cfg.workspace_root == ws_root.resolve()
    assert cfg.resolution_source == "env"


def test_workspace_raises_without_hint(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("HYDROMODPY_WORKSPACE", raising=False)
    project = tmp_path / "standalone_project"
    project.mkdir()
    with pytest.raises(WorkspaceError) as excinfo:
        WorkspaceConfig(project_root=project)
    msg = str(excinfo.value)
    assert "Cannot locate a HydroModPy workspace" in msg
    assert "hmp init" in msg
    assert "HYDROMODPY_WORKSPACE" in msg
    assert "root =" in msg


def test_workspace_catch_name_is_project_dir_name(tmp_path) -> None:
    project = _scaffold(tmp_path / "ws", project="my_project")
    cfg = WorkspaceConfig(project_root=project)
    assert cfg.catch_name == "my_project"


def test_workspace_data_path_from_workspace_root(tmp_path) -> None:
    ws_root = tmp_path / "myworkspace"
    project = _scaffold(ws_root)
    cfg = WorkspaceConfig(project_root=project)
    assert cfg.data_path == (ws_root / "data").resolve()
    assert cfg.catalog_path == (ws_root / "hydromodpy.duckdb").resolve()


def test_workspace_folder_derivation(tmp_path) -> None:
    project = _scaffold(tmp_path / "ws")
    cfg = WorkspaceConfig(project_root=project)
    assert cfg.solver_scratch_folder == project / ".solver_scratch"


def test_workspace_component_override(tmp_path) -> None:
    """An explicit catalog_path infers the workspace root from its parent."""
    ws_root = tmp_path / "ws"
    ws_root.mkdir()
    project = tmp_path / "projectdir"
    project.mkdir()
    custom_catalog = ws_root / "custom.duckdb"
    cfg = WorkspaceConfig(
        project_root=project,
        catalog_path=custom_catalog,
    )
    assert cfg.catalog_path == custom_catalog.resolve()
    assert cfg.workspace_root == ws_root.resolve()
    assert cfg.resolution_source == "explicit"
