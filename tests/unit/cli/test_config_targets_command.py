"""``hmp config targets`` answers what a project can calibrate.

Writing a calibration parameter means writing a dotted path into the
configuration, and the only way to find a valid one was to read the Pydantic
tree. The catalogue is derived from the resolved configuration, so it lists what
THIS project carries, with the value it holds today and the physical range the
registry enforces where it knows one.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from hydromodpy.cli.commands import config as config_cmd

_TOML = textwrap.dedent(
    """
    [workspace]
    project_root = "PROJECT_ROOT"

    [workflow]
    mode = "simulation"

    [geographic]
    source_mode = "synthetic"

    [flow.param.K.field]
    id = "K"
    kind = "homogeneous"
    unit = "m/s"
    value = 6.4e-5

    [flow.param.Sy.field]
    id = "Sy"
    kind = "homogeneous"
    unit = "-"
    value = 0.05
    """
)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    path = tmp_path / "project.toml"
    path.write_text(_TOML.replace("PROJECT_ROOT", str(tmp_path)), encoding="utf-8")
    return path


def _run(project: Path, capsys, *, as_json: bool = False) -> str:
    import argparse

    args = argparse.Namespace(config_command="targets", file=str(project), json=as_json)
    config_cmd.run(args)
    return capsys.readouterr().out


def test_it_names_every_path_a_parameter_may_declare(project, capsys) -> None:
    out = _run(project, capsys)

    assert "flow.param.K.field.value" in out
    assert "flow.param.Sy.field.value" in out


def test_it_shows_the_value_the_project_holds_today(project, capsys) -> None:
    out = _run(project, capsys)

    assert "6.4e-05" in out or "6.4e-5" in out


def test_it_shows_the_physical_range_where_the_registry_knows_one(project, capsys) -> None:
    out = _run(project, capsys)

    assert "0.5" in out  # the specific-yield ceiling


def test_json_output_is_machine_readable(project, capsys) -> None:
    import json

    payload = json.loads(_run(project, capsys, as_json=True))

    paths = {entry["path"] for entry in payload}
    assert "flow.param.K.field.value" in paths
    assert payload[0]["units"] is not None


def test_a_file_that_does_not_load_exits_on_the_config_code(tmp_path, capsys) -> None:
    import argparse

    broken = tmp_path / "broken.toml"
    broken.write_text("[flow]\nnot_a_field = 1\n", encoding="utf-8")

    with pytest.raises(SystemExit) as caught:
        config_cmd.run(argparse.Namespace(config_command="targets", file=str(broken), json=False))

    assert caught.value.code != 0
