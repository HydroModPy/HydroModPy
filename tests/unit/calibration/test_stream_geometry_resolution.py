"""Where a calibration output looks for its mapped stream network.

A path in a TOML is relative to that TOML, the way ``base_config`` is, and a
bare filename falls back to ``<project>/data/hydrography/`` like every other
data path of a project. Read against the working directory instead, the run
depended on where it was launched from and failed on a path that is right.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.calibration.runners.cli_runner import load_toml_calibration

TOML = """\
[workflow]
mode = "calibration"

[calibration]
method = "bisection"

[calibration.parameters.K]
bounds = [1e-9, 1e-3]
transform = "log"
path = "flow.param.K.field.value"

[calibration.outputs.net]
support = "network"
stream_geometry_path = "{declared}"

[[calibration.objective_blocks]]
name = "gap"
metric = "distance_gap"
uses_outputs = ["net"]
"""


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A project holding its network where the convention puts it."""
    geometry = tmp_path / "data" / "hydrography" / "streams.gpkg"
    geometry.parent.mkdir(parents=True)
    geometry.write_bytes(b"not a real gpkg, only its location matters here")
    configs = tmp_path / "configs"
    configs.mkdir()
    return tmp_path


def _load(project: Path, declared: str, *, at: str = "configs") -> str | None:
    path = project / at / "calibration.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TOML.format(declared=declared), encoding="utf-8")
    cfg, _raw = load_toml_calibration(path)
    return cfg.outputs["net"].stream_geometry_path


def test_a_bare_filename_falls_back_to_the_data_family(project: Path) -> None:
    resolved = _load(project, "streams.gpkg")
    assert Path(resolved) == (project / "data" / "hydrography" / "streams.gpkg").resolve()


def test_a_relative_path_is_read_from_the_toml_that_declares_it(project: Path) -> None:
    resolved = _load(project, "../data/hydrography/streams.gpkg")
    assert Path(resolved) == (project / "data" / "hydrography" / "streams.gpkg").resolve()


def test_an_absolute_path_is_left_alone(project: Path) -> None:
    declared = (project / "data" / "hydrography" / "streams.gpkg").resolve()
    assert _load(project, declared.as_posix()) == declared.as_posix()


def test_a_path_that_resolves_to_nothing_is_left_as_declared(project: Path) -> None:
    # Loading a configuration must not require its data: --list-phases has to
    # work on a machine holding none of it, and the criterion names the file it
    # could not read when it gets there.
    assert _load(project, "nowhere.gpkg") == "nowhere.gpkg"
