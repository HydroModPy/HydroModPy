"""A run calibrated by a protocol replays from its own frozen ``config.toml``.

The frozen document carries the ``protocol`` table and the stages it wrote,
and the load compares the two. It used to compare them before the load
writes ``[site] gauge`` into each stage and ``[metrics] window`` into a
transient stage without one, so the stages the run itself had frozen read
as a contradiction of its protocol, and ``hmp catalog rerun`` or
``hmp run --resume`` refused the run.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from hydromodpy.config import HydroModPyConfig
from hydromodpy.core.exceptions import ConfigValidationError
from hydromodpy.workflow.steps.prepare_solver.dispatch import portable_config_document

PROJECT = """\
[site]
name = "nancon"
gauge = "NANCON"

[geographic]
crs_project = "EPSG:2154"

[geographic.catchment]
catch_def = "from_outlet_coord"
dem_init_path = "DEM_armorican_massif.tif"
x_outlet = 389285.9
y_outlet = 6816518.7
snap_dist = "150 m"
buff_area = "10%"

[data]
types = ["hydrography", "hydrometry"]

[[data.hydrography.sources]]
source = "custom"
path = "nancon_stream_network.gpkg"

[[data.hydrometry.sources]]
source = "custom"
path = "hydrometry"
station_ids = ["NANCON"]

[simulation.time]
start_datetime = "{start}"
end_datetime = "{end}"
step_value = 1
step_unit = "month"

[metrics.window]
start = "{start}"
end = "{end}"

[flow]
param_list = ["K", "Sy"]

[flow.param.K.field]
kind = "homogeneous"
unit = "m/s"
value = 5e-5

[flow.param.Sy.field]
kind = "homogeneous"
unit = "-"
value = 0.05

[workflow]
mode = "calibration"

[calibration.parameters.K]
bounds = [1e-7, 1e-3]

[calibration.parameters.Sy]
bounds = [5e-3, 0.35]

[calibration.outputs.seepage_network]
support = "network"
stream_geometry_path = "nancon_stream_network.gpkg"

[calibration.protocol]
name = "matching_hydrographic_network"
"""


def _project(root: Path, *, start: str, end: str) -> Path:
    for relative in (
        "data/dem/DEM_armorican_massif.tif",
        "data/hydrography/nancon_stream_network.gpkg",
    ):
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        (root / relative).write_bytes(b"x")
    (root / "data" / "hydrometry").mkdir(parents=True)
    project = root / "projects" / "nancon"
    project.mkdir(parents=True)
    text = PROJECT.format(start=start, end=end)
    (project / "project.toml").write_text(text, encoding="utf-8")
    return project


def _frozen(project: Path) -> Path:
    cfg = HydroModPyConfig.from_toml(project / "project.toml")
    run_dir = project / "runs" / "nancon"
    run_dir.mkdir(parents=True)
    path = run_dir / "config.toml"
    path.write_text(portable_config_document(cfg, run_dir, project), encoding="utf-8")
    return path


def _phases(cfg: HydroModPyConfig) -> list[dict]:
    return [phase.model_dump(mode="json") for phase in cfg.calibration.phases]


def test_the_gauge_written_into_the_stages_reads_back(tmp_path: Path) -> None:
    project = _project(tmp_path, start="2000-01-01", end="2002-12-31")
    frozen = _frozen(project)
    stages = tomllib.loads(frozen.read_text(encoding="utf-8"))["calibration"]["phases"]
    assert [stage["observed_station_id"] for stage in stages] == ["NANCON", "NANCON"]

    replayed = HydroModPyConfig.from_toml(frozen)

    assert _phases(replayed) == _phases(HydroModPyConfig.from_toml(project / "project.toml"))


def test_the_metrics_window_written_into_the_transient_stage_reads_back(
    tmp_path: Path,
) -> None:
    """A run of one year leaves nothing past the spin-up: ``[metrics] window`` windows it."""
    project = _project(tmp_path, start="2000-01-01", end="2000-12-31")
    frozen = _frozen(project)
    stages = tomllib.loads(frozen.read_text(encoding="utf-8"))["calibration"]["phases"]
    assert stages[1]["scoring_window"]["start"] == "2000-01-01"

    replayed = HydroModPyConfig.from_toml(frozen)

    assert _phases(replayed) == _phases(HydroModPyConfig.from_toml(project / "project.toml"))


def test_a_stage_that_names_another_window_is_still_refused(tmp_path: Path) -> None:
    project = _project(tmp_path, start="2000-01-01", end="2002-12-31")
    frozen = _frozen(project)
    document = tomllib.loads(frozen.read_text(encoding="utf-8"))
    document["calibration"]["phases"][1]["scoring_window"] = {"start": "2002-01-01"}

    with pytest.raises(ConfigValidationError, match="phases"):
        HydroModPyConfig.from_snapshot({**document, "workspace": {"project_root": str(project)}})


def test_a_stage_that_names_another_station_is_still_refused(tmp_path: Path) -> None:
    project = _project(tmp_path, start="2000-01-01", end="2002-12-31")
    frozen = _frozen(project)
    document = tomllib.loads(frozen.read_text(encoding="utf-8"))
    document["calibration"]["phases"][0]["observed_station_id"] = "OTHER"

    with pytest.raises(ConfigValidationError, match="phases"):
        HydroModPyConfig.from_snapshot({**document, "workspace": {"project_root": str(project)}})
