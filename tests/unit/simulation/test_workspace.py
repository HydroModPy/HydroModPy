from pathlib import Path

from hydromodpy.simulation.workspace import Workspace, WorkspaceConfig


def test_workspace_bin_path_resolves_repo_bin(tmp_path) -> None:
    cfg = WorkspaceConfig(
        catch_name="demo",
        out_dir_path=tmp_path / "outputs",
        data_path=tmp_path / "data",
    )
    workspace = Workspace(config=cfg)

    expected = (Path(__file__).resolve().parents[3] / "bin").resolve()
    assert Path(workspace.bin_path).resolve() == expected
