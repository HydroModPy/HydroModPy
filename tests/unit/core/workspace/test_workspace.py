from pathlib import Path

from hydromodpy.core.workspace.config import WorkspaceConfig
from hydromodpy.core.workspace.workspace import WorkspaceLayout


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

    from hydromodpy.core.state.portable import cache_dir

    project = _scaffold(tmp_path / "ws")
    cfg = WorkspaceConfig(project_root=project)
    workspace = WorkspaceLayout(config=cfg)

    assert Path(workspace.bin_path).resolve() == (cache_dir() / "bin").resolve()
