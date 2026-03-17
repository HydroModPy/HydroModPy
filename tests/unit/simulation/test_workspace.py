from pathlib import Path

from hydromodpy.simulation.workspace import Workspace, WorkspaceConfig, WorkspacePathRegistry


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
    assert workspace.paths.stable_folder == workspace.stable_folder
    assert workspace.paths.simulations_folder == workspace.simulations_folder
    assert workspace.paths.calibration_folder == workspace.calibration_folder
    assert workspace.paths.add_data_folder == workspace.add_data_folder
    assert workspace.paths.figures_folder == workspace.figure_folder


def test_workspace_creates_folder_structure(tmp_path) -> None:
    cfg = WorkspaceConfig(
        project_root=tmp_path / "projects" / "demo",
    )
    workspace = Workspace(config=cfg)

    assert workspace.project_root.is_dir()
    assert workspace.stable_folder.is_dir()
    assert workspace.simulations_folder.is_dir()
    assert workspace.calibration_folder.is_dir()
    assert workspace.add_data_folder.is_dir()
    assert workspace.figure_folder.is_dir()


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
    assert cfg.catalog_path == ws_root / "catalog.db"


def test_workspace_data_path_none_without_workspace_root(tmp_path) -> None:
    cfg = WorkspaceConfig(
        project_root=tmp_path / "standalone_project",
    )
    assert cfg.data_path is None
    assert cfg.catalog_path is None


def test_workspace_folder_derivation(tmp_path) -> None:
    project = tmp_path / "projects" / "demo"
    cfg = WorkspaceConfig(project_root=project)
    assert cfg.stable_folder == project / "results_stable"
    assert cfg.simulations_folder == project / "results_simulations"
    assert cfg.calibration_folder == project / "results_calibration"


def test_path_registry_run_folder(tmp_path) -> None:
    registry = WorkspacePathRegistry(project_root=tmp_path / "demo")
    assert registry.run_folder("steady_nwt") == tmp_path / "demo" / "results_simulations" / "steady_nwt"


def test_workspace_catch_folder_alias(tmp_path) -> None:
    cfg = WorkspaceConfig(project_root=tmp_path / "demo")
    workspace = Workspace(config=cfg)
    assert workspace.catch_folder == workspace.project_root
