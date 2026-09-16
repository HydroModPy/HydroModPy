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


def test_an_unresolvable_parameter_name_still_prints_the_catalogue(tmp_path, capsys) -> None:
    """Loading is lenient about a name the catalogue does not carry.

    The refusal a bad name gets (elsewhere) points the reader at this very
    command, so it must not be the thing that refuses to run.
    """
    import argparse

    project = tmp_path / "project.toml"
    project.write_text(
        (_TOML + "\n[calibration.parameters.not_a_real_name]\nbounds = [1e-6, 1e-3]\n").replace(
            "PROJECT_ROOT", str(tmp_path)
        ),
        encoding="utf-8",
    )

    config_cmd.run(argparse.Namespace(config_command="targets", file=str(project), json=False))

    out = capsys.readouterr().out
    assert "flow.param.K.field.value" in out
    assert "Config invalid" not in out


_LAKE_TOML = textwrap.dedent(
    """
    [workspace]
    project_root = "PROJECT_ROOT"

    [workflow]
    mode = "calibration"

    [geographic]
    source_mode = "synthetic"

    [flow]
    active_bc = ["lake"]

    [flow.param.K.field]
    id = "K"
    kind = "homogeneous"
    unit = "m/s"
    value = 6.4e-5

    [flow.sinks_sources.lakes.mylake]
    bedleak = 1e-6
    stageinit = "10 m"

    [calibration]
    method = "optuna"
    max_iter = 4

    [calibration.parameters.bedleak]
    bounds = [1e-8, 1e-5]
    """
)


def test_a_name_that_resolves_only_by_suffix_is_named_with_its_canonical_spelling(
    tmp_path, capsys
) -> None:
    """``bedleak`` reaches ``mylake.bedleak`` today only because it is the only
    target ending in ``.bedleak``. The command names that canonical spelling so
    the file survives a second lake being declared.
    """
    import argparse

    project = tmp_path / "project.toml"
    project.write_text(_LAKE_TOML.replace("PROJECT_ROOT", str(tmp_path)), encoding="utf-8")

    config_cmd.run(argparse.Namespace(config_command="targets", file=str(project), json=False))

    err = capsys.readouterr().err
    assert "calibration.parameters.bedleak" in err
    assert "mylake.bedleak" in err
