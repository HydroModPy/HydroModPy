"""Relative paths of every file of a project are read from the project root."""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.core.toml_io.loader import (
    config_base_dir,
    load_toml_with_base_config,
    read_toml_chain,
)


def test_the_base_is_the_folder_of_project_toml_above_the_file(tmp_path: Path) -> None:
    (tmp_path / "project.toml").write_text("[workspace]\n", encoding="utf-8")
    case = tmp_path / "plan" / "abc123" / "nancon-base.toml"
    case.parent.mkdir(parents=True)
    case.write_text("[workspace]\n", encoding="utf-8")

    assert config_base_dir(case) == tmp_path
    assert config_base_dir(tmp_path / "project.toml") == tmp_path


def test_outside_a_project_the_base_is_the_folder_of_the_root_of_the_chain(tmp_path: Path) -> None:
    (tmp_path / "base.toml").write_text("[workspace]\n", encoding="utf-8")
    child = tmp_path / "sub" / "child.toml"
    child.parent.mkdir()
    child.write_text('base_config = "../base.toml"\n', encoding="utf-8")
    alone = tmp_path / "sub" / "alone.toml"
    alone.write_text("[workspace]\n", encoding="utf-8")

    assert config_base_dir(child) == tmp_path
    assert config_base_dir(alone) == tmp_path / "sub"


def test_the_chain_is_read_root_first_with_the_own_keys_of_each_file(tmp_path: Path) -> None:
    (tmp_path / "base.toml").write_text('[flow]\nflow_regime = "steady"\n', encoding="utf-8")
    (tmp_path / "mid.toml").write_text(
        'base_config = "base.toml"\n[flow]\nparam_list = ["K"]\n', encoding="utf-8"
    )
    leaf = tmp_path / "leaf.toml"
    leaf.write_text(
        'base_config = "mid.toml"\n[flow]\nflow_regime = "transient"\n', encoding="utf-8"
    )

    chain = read_toml_chain(leaf)

    assert [item.path.name for item in chain] == ["base.toml", "mid.toml", "leaf.toml"]
    assert chain[1].own == {"flow": {"param_list": ["K"]}}
    assert "base_config" not in chain[2].own
    assert load_toml_with_base_config(leaf) == {
        "flow": {"flow_regime": "transient", "param_list": ["K"]}
    }


def test_a_cycle_is_refused(tmp_path: Path) -> None:
    (tmp_path / "a.toml").write_text('base_config = "b.toml"\n', encoding="utf-8")
    (tmp_path / "b.toml").write_text('base_config = "a.toml"\n', encoding="utf-8")

    with pytest.raises(ValueError, match="circular base_config chain"):
        read_toml_chain(tmp_path / "a.toml")


def test_a_file_in_a_sub_folder_of_a_project_reads_its_paths_from_the_root(tmp_path: Path) -> None:
    from hydromodpy.config import HydroModPyConfig

    (tmp_path / "project.toml").write_text("[workspace]\n", encoding="utf-8")
    (tmp_path / "data").mkdir()
    sub = tmp_path / "configs_of_runs" / "run.toml"
    sub.parent.mkdir()
    sub.write_text(
        '[workspace]\ndata_dir = "data"\n\n[geographic]\nsource_mode = "synthetic"\n\n'
        '[simulation]\nname = "x"\n\n[[simulation.process]]\nid = "flow_main"\n'
        'type = "flow"\nsolvers = ["modflow6"]\n\n[flow]\nflow_regime = "steady"\n',
        encoding="utf-8",
    )

    cfg = HydroModPyConfig.from_toml(sub)

    assert Path(cfg.workspace.data_dir) == tmp_path / "data"
    assert Path(cfg.workspace.project_root) == tmp_path
