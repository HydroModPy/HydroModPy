"""Where a calibration output looks for its mapped stream network.

A path in a TOML is relative to that TOML, the way ``base_config`` is, and a
bare filename falls back to ``<project>/data/hydrography/`` like every other
data path of a project. Read against the working directory instead, the run
depended on where it was launched from and failed on a path that is right.

The anchoring is done where the CLI, the staged and the programmatic routes
converge, so a configuration built in memory gets it too. That is what the
in-memory test below covers; the TOML-route test beside it guards the older
anchoring in ``load_toml_calibration``, which is a different site.
"""

from __future__ import annotations

from pathlib import Path
from typing import NoReturn

import pytest

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.runners.cli_runner import load_toml_calibration, run_calibration_core
from hydromodpy.calibration.runners.state import space_from_config

_PROJECT_NETWORK = b"the network the project declares"
_DECOY_NETWORK = b"a file of the same name, in the way"

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
    geometry.write_bytes(_PROJECT_NETWORK)
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


@pytest.fixture
def decoy(tmp_path: Path) -> Path:
    """A directory holding another file of the same name, and its sub-path."""
    trap = tmp_path / "elsewhere"
    (trap / "data" / "hydrography").mkdir(parents=True)
    (trap / "streams.gpkg").write_bytes(_DECOY_NETWORK)
    (trap / "data" / "hydrography" / "streams.gpkg").write_bytes(_DECOY_NETWORK)
    return trap


@pytest.mark.parametrize("declared", ["streams.gpkg", "../data/hydrography/streams.gpkg"])
def test_the_network_is_the_same_file_from_any_working_directory(
    project: Path, decoy: Path, monkeypatch: pytest.MonkeyPatch, declared: str
) -> None:
    monkeypatch.chdir(decoy)
    from_decoy = _load(project, declared)
    monkeypatch.chdir(project)
    from_project = _load(project, declared)

    assert from_decoy == from_project
    # Both copies exist under that name; only the project's holds these bytes.
    assert Path(from_decoy).read_bytes() == _PROJECT_NETWORK


class _Halt(Exception):
    """Raised by the store factory to stop the run once the anchoring is done."""


def _halt(*_args: object, **_kwargs: object) -> NoReturn:
    raise _Halt


def _in_memory_config(declared: str) -> CalibrationConfig:
    """The configuration ``Project.calibrate`` builds: no TOML behind it."""
    return CalibrationConfig.model_validate(
        {
            "method": "bisection",
            "parameters": {
                "K": {
                    "bounds": [1e-9, 1e-3],
                    "transform": "log",
                    "path": "flow.param.K.field.value",
                }
            },
            "outputs": {"net": {"support": "network", "stream_geometry_path": declared}},
            "objective_blocks": [
                {"name": "gap", "metric": "distance_gap", "uses_outputs": ["net"]}
            ],
        }
    )


def test_a_route_that_never_reads_a_toml_still_anchors_the_network(
    project: Path, decoy: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Python and embedded modes build the config in memory and reach the runner
    # without going through the TOML loader. Anchoring only there left them
    # reading the working directory.
    cfg = _in_memory_config("streams.gpkg")
    monkeypatch.chdir(decoy)

    with pytest.raises(_Halt):
        run_calibration_core(
            cfg,
            None,
            workspace=project,
            space=space_from_config(cfg),
            cfg_path=project / "project.toml",
            store_factory=_halt,
        )

    assert Path(cfg.outputs["net"].stream_geometry_path).read_bytes() == _PROJECT_NETWORK
