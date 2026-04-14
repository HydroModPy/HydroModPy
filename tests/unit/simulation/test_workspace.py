from pathlib import Path

from hydromodpy.core.workspace import Workspace, WorkspaceConfig, WorkspacePathRegistry


def test_workspace_bin_path_resolves_repo_bin(tmp_path) -> None:
    cfg = WorkspaceConfig(
        project_root=tmp_path / "projects" / "demo",
    )
    workspace = Workspace(config=cfg)

    expected = (Path(__file__).resolve().parents[3] / "bin").resolve()
    assert Path(workspace.bin_path).resolve() == expected


def test_workspace_exposes_canonical_path_registry(tmp_path) -> None:
    cfg = WorkspaceConfig(
        project_root=tmp_path / "projects" / "demo",
    )
    workspace = Workspace(config=cfg)

    assert isinstance(workspace.paths, WorkspacePathRegistry)
    assert workspace.paths.project_root == workspace.project_root
    assert workspace.paths.figures_folder == workspace.figure_folder


def test_workspace_creates_folder_structure(tmp_path) -> None:
    cfg = WorkspaceConfig(
        project_root=tmp_path / "projects" / "demo",
    )
    workspace = Workspace(config=cfg)

    # Only project_root is eagerly created.
    assert workspace.project_root.is_dir()
    assert workspace.solver_scratch_folder == workspace.project_root / ".solver_scratch"


def test_workspace_discovers_workspace_root(tmp_path) -> None:
    ws_root = tmp_path / "myworkspace"
    (ws_root / "projects" / "demo").mkdir(parents=True)
    cfg = WorkspaceConfig(
        project_root=ws_root / "projects" / "demo",
    )
    assert cfg.workspace_root == ws_root


def test_workspace_catch_name_is_project_dir_name(tmp_path) -> None:
    cfg = WorkspaceConfig(
        project_root=tmp_path / "projects" / "my_project",
    )
    assert cfg.catch_name == "my_project"


def test_workspace_data_path_from_workspace_root(tmp_path) -> None:
    ws_root = tmp_path / "myworkspace"
    (ws_root / "projects" / "demo").mkdir(parents=True)
    cfg = WorkspaceConfig(
        project_root=ws_root / "projects" / "demo",
    )
    assert cfg.data_path == ws_root / "data"
    assert cfg.catalog_path == ws_root / "data" / "cache.duckdb"


def test_workspace_data_path_none_without_workspace_root(tmp_path) -> None:
    cfg = WorkspaceConfig(
        project_root=tmp_path / "standalone_project",
    )
    assert cfg.data_path is None
    assert cfg.catalog_path is None


def test_workspace_folder_derivation(tmp_path) -> None:
    project = tmp_path / "projects" / "demo"
    cfg = WorkspaceConfig(project_root=project)
    assert cfg.solver_scratch_folder == project / ".solver_scratch"


def test_workspace_project_root(tmp_path) -> None:
    cfg = WorkspaceConfig(project_root=tmp_path / "demo")
    workspace = Workspace(config=cfg)
    assert workspace.project_root == tmp_path / "demo"
