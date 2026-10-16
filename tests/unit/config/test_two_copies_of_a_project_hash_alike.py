"""A path of the configuration enters the run identity relative to the project root."""

from __future__ import annotations

import shutil
from pathlib import Path

from hydromodpy.config import HydroModPyConfig
from hydromodpy.results.catalog.registration import input_file_digests, run_identity_hash

PROJECT = """\
[geographic]
source_mode = "synthetic"

[data]
types = ["recharge"]

[[data.recharge.sources]]
source = "custom"
path = "inputs/recharge.csv"
"""


def _project(root: Path) -> Path:
    (root / "inputs").mkdir(parents=True)
    (root / "inputs" / "recharge.csv").write_text("date,value\n2000-01-01,1\n", encoding="utf-8")
    (root / "project.toml").write_text(PROJECT, encoding="utf-8")
    return root / "project.toml"


def _config_hash(path: Path) -> str | None:
    cfg = HydroModPyConfig.from_toml(path)
    return run_identity_hash(cfg.model_dump(mode="json"), inputs=input_file_digests(cfg))


def test_two_copies_of_one_project_give_one_config_hash(tmp_path: Path) -> None:
    first = _project(tmp_path / "here" / "nancon")
    copy = tmp_path / "elsewhere" / "deeper" / "nancon"
    shutil.copytree(first.parent, copy)

    loaded = HydroModPyConfig.from_toml(first)
    assert Path(loaded.data.recharge.sources[0].path).is_absolute()
    assert _config_hash(first) == _config_hash(copy / "project.toml")


def test_a_path_outside_the_project_stays_what_it_names() -> None:
    def config(root: str, data: str) -> dict:
        return {
            "workspace": {"project_root": root},
            "data": {"recharge": {"sources": [{"path": data}]}},
        }

    inside = run_identity_hash(config("/a/proj", "/a/proj/in.csv"))
    assert inside == run_identity_hash(config("/b/c/proj", "/b/c/proj/in.csv"))
    outside = run_identity_hash(config("/a/proj", "/shared/in.csv"))
    assert outside == run_identity_hash(config("/b/c/proj", "/shared/in.csv"))
    assert outside != run_identity_hash(config("/a/proj", "/other/in.csv"))
