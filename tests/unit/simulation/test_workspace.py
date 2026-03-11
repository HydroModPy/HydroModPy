from pathlib import Path

from hydromodpy.simulation.workspace import Workspace, WorkspaceConfig, WorkspacePathRegistry


def test_workspace_bin_path_resolves_repo_bin(tmp_path) -> None:
    cfg = WorkspaceConfig(
        catch_name="demo",
        out_dir_path=tmp_path / "outputs",
        data_path=tmp_path / "data",
    )
    workspace = Workspace(config=cfg)

    expected = (Path(__file__).resolve().parents[3] / "bin").resolve()
    assert Path(workspace.bin_path).resolve() == expected


def test_workspace_exposes_canonical_path_registry(tmp_path) -> None:
    cfg = WorkspaceConfig(
        catch_name="demo",
        out_dir_path=tmp_path / "outputs",
        data_path=tmp_path / "data",
    )
    workspace = Workspace(config=cfg)

    assert isinstance(workspace.paths, WorkspacePathRegistry)
    assert workspace.paths.catch_folder == workspace.catch_folder
    assert workspace.paths.stable_folder == workspace.stable_folder
    assert workspace.paths.simulations_folder == workspace.simulations_folder
    assert workspace.paths.calibration_folder == workspace.calibration_folder
    assert workspace.paths.add_data_folder == workspace.add_data_folder
    assert workspace.paths.figures_folder == workspace.figure_folder
    assert workspace.data_path == cfg.data_path
