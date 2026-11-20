"""Request id of a project file (a hash of its resolved configuration).

A path of the configuration enters the id relative to the project root, so two
copies of one workspace on two machines give the same id.
"""

from __future__ import annotations

from pathlib import Path

from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.data.loading.inputs import ResolvedInputs
from hydromodpy.workflow.solution_key import request_id_of

PROJECT_TOML = """\
[geographic]
source_mode = "synthetic"

[data]
types = ["recharge"]

[[data.recharge.sources]]
source = "file"
path = "{path}"
"""


def workspace_project(
    root: Path, *, path: str = "../../data/recharge/recharge_custom_basin.csv"
) -> Path:
    """Write a workspace holding one project and one recharge file, return its project.toml."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "workspace.toml").write_text("[workspace]\n", encoding="utf-8")
    data = root / "data" / "recharge"
    data.mkdir(parents=True)
    (data / "recharge_custom_basin.csv").write_text("date,value\n2000-01-01,1\n", encoding="utf-8")
    project = root / "projects" / "nancon"
    project.mkdir(parents=True)
    (project / "project.toml").write_text(PROJECT_TOML.format(path=path), encoding="utf-8")
    return project / "project.toml"


def config_hash(path: Path) -> str:
    cfg = HydroModPyConfig.from_toml(path)
    return request_id_of(cfg, ResolvedInputs(), search=True)


def test_two_workspaces_give_one_hash(tmp_path: Path) -> None:
    first = workspace_project(tmp_path / "laptop" / "ws")
    second = workspace_project(tmp_path / "cluster" / "deep" / "ws")

    loaded = HydroModPyConfig.from_toml(first)
    assert Path(loaded.data.recharge.sources[0].path).is_relative_to(tmp_path / "laptop")
    assert config_hash(first) == config_hash(second)


def test_a_sidecar_file_keeps_the_hash(tmp_path: Path) -> None:
    project = workspace_project(tmp_path / "ws", path="../../data/recharge")
    before = config_hash(project)
    data = tmp_path / "ws" / "data" / "recharge"
    (data / "recharge_custom_basin.csv.json").write_text('{"source": "file"}', encoding="utf-8")

    assert config_hash(project) == before
