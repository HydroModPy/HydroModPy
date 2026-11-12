"""A path of the configuration enters the request id relative to the project root."""

from __future__ import annotations

import shutil
from pathlib import Path

from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.data.loading.inputs import ResolvedInputs
from hydromodpy.results.record.request_identity import request_id
from hydromodpy.workflow.solution_key import request_id_of

PROJECT = """\
[geographic]
source_mode = "synthetic"

[data]
types = ["recharge"]

[[data.recharge.sources]]
source = "file"
path = "inputs/recharge.csv"
"""


def _project(root: Path) -> Path:
    (root / "inputs").mkdir(parents=True)
    (root / "inputs" / "recharge.csv").write_text("date,value\n2000-01-01,1\n", encoding="utf-8")
    (root / "project.toml").write_text(PROJECT, encoding="utf-8")
    return root / "project.toml"


EDITION = "2.0"


def _config_hash(path: Path) -> str:
    """Return the request id of the file, its inputs read from the files they name."""
    cfg = HydroModPyConfig.from_toml(path)
    return request_id_of(cfg, ResolvedInputs(), search=True)


def test_two_copies_of_one_project_give_one_config_hash(tmp_path: Path) -> None:
    first = _project(tmp_path / "here" / "nancon")
    copy = tmp_path / "elsewhere" / "deeper" / "nancon"
    shutil.copytree(first.parent, copy)

    loaded = HydroModPyConfig.from_toml(first)
    assert Path(loaded.data.recharge.sources[0].path).is_absolute()
    assert _config_hash(first) == _config_hash(copy / "project.toml")


def request_id_of_document(document: dict) -> str:
    return request_id(document, {}, edition=EDITION)


def test_a_path_outside_the_project_stays_what_it_names() -> None:
    def config(root: str, data: str) -> dict:
        return {
            "workspace": {"project_root": root},
            "data": {"recharge": {"sources": [{"path": data}]}},
        }

    inside = request_id_of_document(config("/a/proj", "/a/proj/in.csv"))
    assert inside == request_id_of_document(config("/b/c/proj", "/b/c/proj/in.csv"))
    outside = request_id_of_document(config("/a/proj", "/shared/in.csv"))
    assert outside == request_id_of_document(config("/b/c/proj", "/shared/in.csv"))
    assert outside != request_id_of_document(config("/a/proj", "/other/in.csv"))


WORKSPACE_PROJECT = """\
[geographic]
source_mode = "synthetic"

[data]
types = ["recharge"]

[[data.recharge.sources]]
source = "file"
path = "{path}"
"""


def _workspace_project(
    root: Path, *, path: str = "../../data/recharge/recharge_custom_basin.csv"
) -> Path:
    (root / "workspace.toml").parent.mkdir(parents=True, exist_ok=True)
    (root / "workspace.toml").write_text("[workspace]\n", encoding="utf-8")
    data = root / "data" / "recharge"
    data.mkdir(parents=True)
    (data / "recharge_custom_basin.csv").write_text("date,value\n2000-01-01,1\n", encoding="utf-8")
    project = root / "projects" / "nancon"
    project.mkdir(parents=True)
    (project / "project.toml").write_text(WORKSPACE_PROJECT.format(path=path), encoding="utf-8")
    return project / "project.toml"


def test_two_workspaces_holding_the_same_data_give_one_config_hash(tmp_path: Path) -> None:
    first = _workspace_project(tmp_path / "laptop" / "ws")
    second = _workspace_project(tmp_path / "cluster" / "deep" / "ws")

    loaded = HydroModPyConfig.from_toml(first)
    assert Path(loaded.data.recharge.sources[0].path).is_relative_to(tmp_path / "laptop")
    assert _config_hash(first) == _config_hash(second)


def test_a_sidecar_in_a_declared_folder_leaves_the_hash_as_it_was(tmp_path: Path) -> None:
    project = _workspace_project(tmp_path / "ws", path="../../data/recharge")
    before = _config_hash(project)
    data = tmp_path / "ws" / "data" / "recharge"
    (data / "recharge_custom_basin.csv.json").write_text('{"source": "file"}', encoding="utf-8")

    assert _config_hash(project) == before
